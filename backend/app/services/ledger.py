from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException, status
from sqlalchemy import case, func
from sqlalchemy.orm import Session, selectinload

from app.models import (
    CashMovement,
    Customer,
    InventoryMovement,
    Product,
    Supplier,
    Transaction,
    TransactionItem,
)
from app.schemas import (
    CashMovementOut,
    InventoryMovementOut,
    OpeningCashCreate,
    OpeningStockCreate,
    PaymentCreate,
    TransactionCreate,
    TransactionItemOut,
    TransactionOut,
)

Q4 = Decimal("0.0001")
ZERO = Decimal("0.0000")
OPENING_CASH_IDEMPOTENCY_KEY = "opening-cash"
PAYABLE_TX_TYPES = ("sale", "purchase", "expense")
RETURN_TX_TYPES = ("sale_return", "purchase_return")


def q4(value: Decimal) -> Decimal:
    """Quantize monetary and quantity values to 4 decimal places."""
    return value.quantize(Q4, rounding=ROUND_HALF_UP)


def _compute_weighted_avg_cost(
    on_hand: Decimal,
    current_avg_cost: Decimal,
    added_qty: Decimal,
    unit_cost: Decimal,
) -> Decimal:
    """Compute weighted-average unit cost, resetting to unit_cost when on_hand <= 0."""
    if on_hand <= ZERO:
        return q4(unit_cost)
    total_qty = on_hand + added_qty
    if total_qty <= ZERO:
        return q4(unit_cost)
    total_value = (on_hand * current_avg_cost) + (added_qty * unit_cost)
    return q4(total_value / total_qty)


def _load_locked_products(
    db: Session,
    business_id: uuid.UUID,
    product_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Product]:
    """Lock referenced products in deterministic ID order and verify tenant ownership."""
    unique_ids = sorted(set(product_ids))
    if not unique_ids:
        return {}
    products = (
        db.query(Product)
        .filter(Product.business_id == business_id, Product.id.in_(unique_ids))
        .order_by(Product.id.asc())
        .with_for_update()
        .all()
    )
    if len(products) != len(unique_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more products were not found in this business",
        )
    return {p.id: p for p in products}


def _get_on_hand_map(
    db: Session,
    business_id: uuid.UUID,
    product_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Decimal]:
    """Fetch current on-hand stock quantities for the requested products."""
    if not product_ids:
        return {}
    rows = (
        db.query(
            InventoryMovement.product_id,
            func.coalesce(func.sum(InventoryMovement.qty_delta), ZERO),
        )
        .filter(
            InventoryMovement.business_id == business_id,
            InventoryMovement.product_id.in_(product_ids),
        )
        .group_by(InventoryMovement.product_id)
        .all()
    )
    on_hand: dict[uuid.UUID, Decimal] = {pid: ZERO for pid in product_ids}
    for pid, qty in rows:
        on_hand[pid] = q4(Decimal(qty))
    return on_hand


def _validate_party_ownership(
    db: Session,
    business_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    supplier_id: uuid.UUID | None,
) -> None:
    if customer_id is not None:
        exists = (
            db.query(Customer.id)
            .filter(Customer.id == customer_id, Customer.business_id == business_id)
            .first()
        )
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found in this business",
            )
    if supplier_id is not None:
        exists = (
            db.query(Supplier.id)
            .filter(Supplier.id == supplier_id, Supplier.business_id == business_id)
            .first()
        )
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Supplier not found in this business",
            )


def _signed_payment_amount(tx_type: str, amount: Decimal) -> Decimal:
    """Map positive payment/refund magnitude to CashMovement.signed_amount."""
    if tx_type in ("sale", "purchase_return"):
        return q4(amount)
    return -q4(amount)


def _cash_to_paid(tx_type: str, net_signed_cash: Decimal) -> Decimal:
    if tx_type in ("sale", "purchase_return"):
        return q4(net_signed_cash)
    return q4(-net_signed_cash)


def _get_tx_settlement(
    db: Session,
    business_id: uuid.UUID,
    tx: Transaction,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (amount_paid, returns_total, balance_due) for a single transaction."""
    net_cash = db.query(func.coalesce(func.sum(CashMovement.signed_amount), ZERO)).filter(
        CashMovement.business_id == business_id,
        CashMovement.transaction_id == tx.id,
    ).scalar() or ZERO
    amount_paid = _cash_to_paid(tx.type, Decimal(net_cash))

    if tx.type in RETURN_TX_TYPES:
        return amount_paid, ZERO, ZERO

    returns_total = db.query(func.coalesce(func.sum(Transaction.total), ZERO)).filter(
        Transaction.business_id == business_id,
        Transaction.original_transaction_id == tx.id,
        Transaction.status == "posted",
    ).scalar() or ZERO
    returns_total_q = q4(Decimal(returns_total))
    balance_due = max(ZERO, q4(tx.total - returns_total_q - amount_paid))
    return amount_paid, returns_total_q, balance_due


def _build_transaction_out(
    tx: Transaction,
    amount_paid: Decimal,
    returns_total: Decimal,
    balance_due: Decimal,
) -> TransactionOut:
    return TransactionOut(
        id=tx.id,
        business_id=tx.business_id,
        type=tx.type,
        original_transaction_id=tx.original_transaction_id,
        customer_id=tx.customer_id,
        supplier_id=tx.supplier_id,
        date=tx.date,
        due_date=tx.due_date,
        total=tx.total,
        discount=tx.discount,
        status=tx.status,
        idempotency_key=tx.idempotency_key,
        notes=tx.notes,
        created_at=tx.created_at,
        amount_paid=amount_paid,
        returns_total=returns_total,
        balance_due=balance_due,
        items=[TransactionItemOut.model_validate(item) for item in tx.items],
    )


def get_transaction_out(
    db: Session,
    business_id: uuid.UUID,
    transaction_id: uuid.UUID,
) -> TransactionOut:
    tx = (
        db.query(Transaction)
        .options(selectinload(Transaction.items))
        .filter(Transaction.id == transaction_id, Transaction.business_id == business_id)
        .first()
    )
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found in this business",
        )
    amount_paid, returns_total, balance_due = _get_tx_settlement(db, business_id, tx)
    return _build_transaction_out(tx, amount_paid, returns_total, balance_due)


def _create_return_transaction(
    db: Session,
    business_id: uuid.UUID,
    payload: TransactionCreate,
) -> TransactionOut:
    if payload.original_transaction_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Return transactions require original_transaction_id",
        )
    if payload.paid_amount > ZERO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Do not pass paid_amount on returns; refunds are calculated automatically",
        )
    if payload.discount > ZERO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Discounts cannot be applied to return transactions",
        )
    if payload.expense_amount is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="expense_amount is only valid for expense transactions",
        )
    if not payload.items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Return transactions require at least one item",
        )

    orig = (
        db.query(Transaction)
        .options(selectinload(Transaction.items))
        .filter(
            Transaction.id == payload.original_transaction_id,
            Transaction.business_id == business_id,
        )
        .with_for_update()
        .first()
    )
    if orig is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original transaction not found in this business",
        )
    expected_orig_type = "sale" if payload.type == "sale_return" else "purchase"
    if orig.status != "posted" or orig.type != expected_orig_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{payload.type} must reference a posted {expected_orig_type}",
        )

    orig_items_by_pid: dict[uuid.UUID, TransactionItem] = {}
    for item in orig.items:
        if item.product_id is not None:
            orig_items_by_pid[item.product_id] = item

    prior_returns = (
        db.query(Transaction)
        .options(selectinload(Transaction.items))
        .filter(
            Transaction.business_id == business_id,
            Transaction.original_transaction_id == orig.id,
            Transaction.status == "posted",
        )
        .all()
    )
    already_returned_qty: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    prior_returns_total = ZERO
    for ret in prior_returns:
        prior_returns_total += Decimal(ret.total)
        for ret_item in ret.items:
            if ret_item.product_id is not None:
                already_returned_qty[ret_item.product_id] += Decimal(ret_item.qty)

    item_product_ids: list[uuid.UUID] = []
    for req_item in payload.items:
        if req_item.product_id is None or req_item.product_id not in orig_items_by_pid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Returned items must reference a product from the original transaction",
            )
        item_product_ids.append(req_item.product_id)

    products_by_id = _load_locked_products(db, business_id, item_product_ids)
    on_hand = _get_on_hand_map(db, business_id, list(products_by_id.keys()))

    pending_return_qty: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    prepared_items: list[tuple[Product, Decimal, Decimal, Decimal]] = []
    subtotal = ZERO

    for req_item in payload.items:
        pid = req_item.product_id
        assert pid is not None
        orig_item = orig_items_by_pid[pid]
        product = products_by_id[pid]
        qty = q4(req_item.qty)
        pending_return_qty[pid] += qty

        max_returnable = q4(Decimal(orig_item.qty) - already_returned_qty[pid])
        if pending_return_qty[pid] > max_returnable:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Returned quantity for '{product.sku}' exceeds remaining returnable quantity",
            )

        unit_price = (
            q4(req_item.unit_price)
            if req_item.unit_price is not None
            else q4(Decimal(orig_item.unit_price))
        )
        unit_cost_snapshot = q4(Decimal(orig_item.unit_cost_snapshot))

        if payload.type == "purchase_return" and product.track_inventory:
            if on_hand[pid] < qty:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Insufficient stock to return '{product.sku}'",
                )
            on_hand[pid] = q4(on_hand[pid] - qty)
        elif payload.type == "sale_return" and product.track_inventory:
            on_hand[pid] = q4(on_hand[pid] + qty)

        subtotal += q4(qty * unit_price)
        prepared_items.append((product, qty, unit_price, unit_cost_snapshot))

    ret_total = q4(subtotal)
    remaining_orig_returnable = max(ZERO, q4(Decimal(orig.total) - prior_returns_total))
    if ret_total > remaining_orig_returnable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Return total exceeds remaining non-returned amount of original transaction",
        )

    orig_paid, _, orig_balance_before = _get_tx_settlement(db, business_id, orig)
    _ = orig_paid
    credit_applied = min(ret_total, max(ZERO, orig_balance_before))
    refund_amount = q4(ret_total - credit_applied)

    ret_tx = Transaction(
        business_id=business_id,
        type=payload.type,
        original_transaction_id=orig.id,
        customer_id=orig.customer_id,
        supplier_id=orig.supplier_id,
        date=payload.date,
        due_date=None,
        total=ret_total,
        discount=ZERO,
        status="posted",
        idempotency_key=payload.idempotency_key,
        notes=payload.notes,
    )
    db.add(ret_tx)
    db.flush()

    for product, qty, unit_price, unit_cost_snapshot in prepared_items:
        db.add(
            TransactionItem(
                transaction_id=ret_tx.id,
                product_id=product.id,
                qty=qty,
                unit_price=unit_price,
                unit_cost_snapshot=unit_cost_snapshot,
            )
        )
        if product.track_inventory:
            qty_delta = qty if payload.type == "sale_return" else -qty
            db.add(
                InventoryMovement(
                    business_id=business_id,
                    product_id=product.id,
                    qty_delta=qty_delta,
                    unit_cost=unit_cost_snapshot,
                    type="return",
                    transaction_id=ret_tx.id,
                )
            )

    if refund_amount > ZERO:
        db.add(
            CashMovement(
                business_id=business_id,
                date=payload.date,
                signed_amount=_signed_payment_amount(payload.type, refund_amount),
                transaction_id=ret_tx.id,
                idempotency_key=(
                    f"{payload.idempotency_key}:refund" if payload.idempotency_key else None
                ),
                note=f"Auto refund for {payload.type} of {orig.id}",
            )
        )

    db.flush()
    return get_transaction_out(db, business_id, ret_tx.id)


def _create_standard_transaction(
    db: Session,
    business_id: uuid.UUID,
    payload: TransactionCreate,
) -> TransactionOut:
    if payload.original_transaction_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="original_transaction_id is only allowed on return transactions",
        )

    _validate_party_ownership(db, business_id, payload.customer_id, payload.supplier_id)

    if payload.type == "expense":
        if not payload.items and payload.expense_amount is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Expense requires either items or expense_amount",
            )
        if payload.items and payload.expense_amount is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Provide either items or expense_amount, not both",
            )
    else:
        if payload.expense_amount is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="expense_amount is only valid for expense transactions",
            )
        if not payload.items:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{payload.type} requires at least one item",
            )

    product_ids = [item.product_id for item in payload.items if item.product_id is not None]
    products_by_id = _load_locked_products(db, business_id, product_ids)
    on_hand = _get_on_hand_map(db, business_id, list(products_by_id.keys()))

    prepared_items: list[tuple[uuid.UUID | None, Decimal, Decimal, Decimal]] = []
    subtotal = ZERO

    if payload.items:
        for req_item in payload.items:
            qty = q4(req_item.qty)
            if req_item.product_id is None:
                if req_item.unit_price is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="unit_price is required when product_id is omitted",
                    )
                unit_price = q4(req_item.unit_price)
                unit_cost_snapshot = unit_price if payload.type in ("purchase", "expense") else ZERO
                subtotal += q4(qty * unit_price)
                prepared_items.append((None, qty, unit_price, unit_cost_snapshot))
                continue

            product = products_by_id[req_item.product_id]
            if req_item.unit_price is not None:
                unit_price = q4(req_item.unit_price)
            elif payload.type == "sale":
                unit_price = q4(Decimal(product.sale_price))
            else:
                unit_price = q4(Decimal(product.avg_cost))

            if payload.type == "sale":
                if product.track_inventory:
                    if on_hand[product.id] < qty:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Insufficient stock for product '{product.sku}'",
                        )
                    on_hand[product.id] = q4(on_hand[product.id] - qty)
                unit_cost_snapshot = q4(Decimal(product.avg_cost))
            elif payload.type == "purchase":
                if product.track_inventory:
                    new_avg = _compute_weighted_avg_cost(
                        on_hand=on_hand[product.id],
                        current_avg_cost=Decimal(product.avg_cost),
                        added_qty=qty,
                        unit_cost=unit_price,
                    )
                    product.avg_cost = new_avg
                    on_hand[product.id] = q4(on_hand[product.id] + qty)
                unit_cost_snapshot = unit_price
            else:
                unit_cost_snapshot = unit_price

            subtotal += q4(qty * unit_price)
            prepared_items.append((product.id, qty, unit_price, unit_cost_snapshot))
    else:
        assert payload.expense_amount is not None
        subtotal = q4(payload.expense_amount)

    discount = q4(payload.discount)
    if discount > subtotal:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Discount cannot exceed subtotal",
        )

    total = q4(subtotal - discount)
    paid_amount = q4(payload.paid_amount)
    if paid_amount > total:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="paid_amount cannot exceed transaction total",
        )

    balance_due = q4(total - paid_amount)
    due_date = payload.due_date
    if balance_due > ZERO:
        if payload.type == "sale" and payload.customer_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Credit sales with unpaid balance require customer_id",
            )
        if payload.type == "purchase" and payload.supplier_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Credit purchases with unpaid balance require supplier_id",
            )
        if due_date is None:
            default_days = 14 if payload.type == "sale" else 30
            due_date = payload.date + dt.timedelta(days=default_days)

    tx = Transaction(
        business_id=business_id,
        type=payload.type,
        original_transaction_id=None,
        customer_id=payload.customer_id,
        supplier_id=payload.supplier_id,
        date=payload.date,
        due_date=due_date,
        total=total,
        discount=discount,
        status="posted",
        idempotency_key=payload.idempotency_key,
        notes=payload.notes,
    )
    db.add(tx)
    db.flush()

    for pid, qty, unit_price, unit_cost_snapshot in prepared_items:
        db.add(
            TransactionItem(
                transaction_id=tx.id,
                product_id=pid,
                qty=qty,
                unit_price=unit_price,
                unit_cost_snapshot=unit_cost_snapshot,
            )
        )
        if pid is not None:
            product = products_by_id[pid]
            if product.track_inventory and payload.type in ("sale", "purchase"):
                qty_delta = -qty if payload.type == "sale" else qty
                db.add(
                    InventoryMovement(
                        business_id=business_id,
                        product_id=pid,
                        qty_delta=qty_delta,
                        unit_cost=unit_cost_snapshot,
                        type=payload.type,
                        transaction_id=tx.id,
                    )
                )

    if paid_amount > ZERO:
        db.add(
            CashMovement(
                business_id=business_id,
                date=payload.date,
                signed_amount=_signed_payment_amount(payload.type, paid_amount),
                transaction_id=tx.id,
                idempotency_key=(
                    f"{payload.idempotency_key}:initial" if payload.idempotency_key else None
                ),
                note=f"Initial payment for {payload.type}",
            )
        )

    db.flush()
    return get_transaction_out(db, business_id, tx.id)


def create_transaction(
    db: Session,
    business_id: uuid.UUID,
    payload: TransactionCreate,
) -> TransactionOut:
    """Create and post a transaction idempotently without committing."""
    if payload.idempotency_key is not None:
        existing = (
            db.query(Transaction)
            .filter(
                Transaction.business_id == business_id,
                Transaction.idempotency_key == payload.idempotency_key,
            )
            .first()
        )
        if existing is not None:
            return get_transaction_out(db, business_id, existing.id)

    if payload.type in RETURN_TX_TYPES:
        return _create_return_transaction(db, business_id, payload)
    return _create_standard_transaction(db, business_id, payload)


def record_payment(
    db: Session,
    business_id: uuid.UUID,
    transaction_id: uuid.UUID,
    payload: PaymentCreate,
) -> CashMovementOut:
    """Record an idempotent partial or full cash payment against an open transaction."""
    existing = (
        db.query(CashMovement)
        .filter(
            CashMovement.business_id == business_id,
            CashMovement.idempotency_key == payload.idempotency_key,
        )
        .first()
    )
    if existing is not None:
        if existing.transaction_id != transaction_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key already used for a different transaction",
            )
        return CashMovementOut.model_validate(existing)

    tx = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id, Transaction.business_id == business_id)
        .with_for_update()
        .first()
    )
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found in this business",
        )
    if tx.status != "posted" or tx.type not in PAYABLE_TX_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Payments are only allowed on posted sale, purchase, or expense transactions",
        )

    _, _, balance_due = _get_tx_settlement(db, business_id, tx)
    amount = q4(payload.amount)
    if amount > balance_due:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment amount exceeds remaining balance due",
        )

    movement = CashMovement(
        business_id=business_id,
        date=payload.date,
        signed_amount=_signed_payment_amount(tx.type, amount),
        transaction_id=tx.id,
        idempotency_key=payload.idempotency_key,
        note=payload.note or f"Payment for {tx.type}",
    )
    db.add(movement)
    db.flush()
    return CashMovementOut.model_validate(movement)


def set_opening_cash(
    db: Session,
    business_id: uuid.UUID,
    payload: OpeningCashCreate,
) -> CashMovementOut:
    """Upsert the business's single opening-cash movement without double-counting."""
    existing = (
        db.query(CashMovement)
        .filter(
            CashMovement.business_id == business_id,
            CashMovement.idempotency_key == OPENING_CASH_IDEMPOTENCY_KEY,
        )
        .first()
    )
    amount = q4(payload.amount)
    if existing is not None:
        existing.date = payload.date
        existing.signed_amount = amount
        existing.note = payload.note or "Opening cash"
        db.flush()
        return CashMovementOut.model_validate(existing)

    movement = CashMovement(
        business_id=business_id,
        date=payload.date,
        signed_amount=amount,
        transaction_id=None,
        idempotency_key=OPENING_CASH_IDEMPOTENCY_KEY,
        note=payload.note or "Opening cash",
    )
    db.add(movement)
    db.flush()
    return CashMovementOut.model_validate(movement)


def set_opening_stock(
    db: Session,
    business_id: uuid.UUID,
    payload: OpeningStockCreate,
) -> InventoryMovementOut:
    """Post opening stock for a tracked inventory product and update weighted-average cost."""
    products = _load_locked_products(db, business_id, [payload.product_id])
    product = products[payload.product_id]
    if not product.track_inventory:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Opening stock can only be recorded for inventory-tracked products",
        )

    on_hand = _get_on_hand_map(db, business_id, [product.id])[product.id]
    qty = q4(payload.qty)
    unit_cost = q4(payload.unit_cost)
    product.avg_cost = _compute_weighted_avg_cost(
        on_hand=on_hand,
        current_avg_cost=Decimal(product.avg_cost),
        added_qty=qty,
        unit_cost=unit_cost,
    )

    movement = InventoryMovement(
        business_id=business_id,
        product_id=product.id,
        qty_delta=qty,
        unit_cost=unit_cost,
        type="opening",
        transaction_id=None,
    )
    db.add(movement)
    db.flush()
    return InventoryMovementOut.model_validate(movement)


def list_transactions(
    db: Session,
    business_id: uuid.UUID,
    tx_type: str | None = None,
    customer_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    unpaid_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[TransactionOut]:
    """List tenant transactions with grouped-subquery balances (no N+1 queries)."""
    cash_subq = (
        db.query(
            CashMovement.transaction_id.label("tx_id"),
            func.coalesce(func.sum(CashMovement.signed_amount), ZERO).label("net_cash"),
        )
        .filter(
            CashMovement.business_id == business_id,
            CashMovement.transaction_id.is_not(None),
        )
        .group_by(CashMovement.transaction_id)
        .subquery()
    )

    returns_subq = (
        db.query(
            Transaction.original_transaction_id.label("orig_id"),
            func.coalesce(func.sum(Transaction.total), ZERO).label("returns_total"),
        )
        .filter(
            Transaction.business_id == business_id,
            Transaction.original_transaction_id.is_not(None),
            Transaction.status == "posted",
        )
        .group_by(Transaction.original_transaction_id)
        .subquery()
    )

    net_cash_col = func.coalesce(cash_subq.c.net_cash, ZERO)
    amount_paid_expr = case(
        (Transaction.type.in_(["sale", "purchase_return"]), net_cash_col),
        else_=-net_cash_col,
    )
    returns_expr = case(
        (Transaction.type.in_(RETURN_TX_TYPES), ZERO),
        else_=func.coalesce(returns_subq.c.returns_total, ZERO),
    )
    raw_balance = Transaction.total - returns_expr - amount_paid_expr
    balance_due_expr = case(
        (Transaction.type.in_(RETURN_TX_TYPES), ZERO),
        (raw_balance < ZERO, ZERO),
        else_=raw_balance,
    )

    query = (
        db.query(
            Transaction,
            amount_paid_expr.label("amount_paid"),
            returns_expr.label("returns_total"),
            balance_due_expr.label("balance_due"),
        )
        .options(selectinload(Transaction.items))
        .outerjoin(cash_subq, cash_subq.c.tx_id == Transaction.id)
        .outerjoin(returns_subq, returns_subq.c.orig_id == Transaction.id)
        .filter(Transaction.business_id == business_id)
    )

    if tx_type is not None:
        query = query.filter(Transaction.type == tx_type)
    if customer_id is not None:
        query = query.filter(Transaction.customer_id == customer_id)
    if supplier_id is not None:
        query = query.filter(Transaction.supplier_id == supplier_id)
    if date_from is not None:
        query = query.filter(Transaction.date >= date_from)
    if date_to is not None:
        query = query.filter(Transaction.date <= date_to)
    if unpaid_only:
        query = query.filter(Transaction.status == "posted", balance_due_expr > ZERO)

    rows = (
        query.order_by(Transaction.date.desc(), Transaction.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        _build_transaction_out(
            tx=tx,
            amount_paid=q4(Decimal(paid)),
            returns_total=q4(Decimal(ret)),
            balance_due=q4(Decimal(bal)),
        )
        for tx, paid, ret, bal in rows
    ]
