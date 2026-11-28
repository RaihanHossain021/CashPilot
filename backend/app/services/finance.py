"""Deterministic financial calculations for cash, dues, stock, margins, and coverage.

Note: Purchases are NOT expenses. Inventory enters profit and loss only when sold
via COGS (unit_cost_snapshot), and expenses sum only ``type == 'expense'`` transactions.
All calculations keep full Decimal precision during intermediate steps and quantize
once at the end of each output metric.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models import (
    Business,
    CashMovement,
    Customer,
    InventoryMovement,
    Product,
    Supplier,
    Transaction,
    TransactionItem,
)
from app.schemas import (
    InventoryItemOut,
    InventoryResponse,
    ProductMarginOut,
    ProfitabilityResponse,
)

Q4 = Decimal("0.0001")
ZERO = Decimal("0.0000")
NEW_STOCK_GRACE_DAYS = 14


def q4(value: Decimal) -> Decimal:
    """Quantize a Decimal value once to 4 decimal places."""
    return value.quantize(Q4, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class OpenTransactionBalance:
    transaction_id: uuid.UUID
    tx_type: str
    party_id: uuid.UUID | None
    party_name: str | None
    date: dt.date
    due_date: dt.date | None
    total: Decimal
    amount_paid: Decimal
    returns_total: Decimal
    balance_due: Decimal
    overdue: bool


def _resolve_as_of(as_of: dt.date | None) -> dt.date:
    return as_of or dt.date.today()


def get_cash_position(
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date | None = None,
) -> dict[str, object]:
    """Compute cash on hand and opening-cash completeness up to as_of."""
    ref_date = _resolve_as_of(as_of)
    business = db.get(Business, business_id)
    assert business is not None

    raw_cash = db.query(func.coalesce(func.sum(CashMovement.signed_amount), ZERO)).filter(
        CashMovement.business_id == business_id,
        CashMovement.date <= ref_date,
    ).scalar() or ZERO

    opening_exists = (
        db.query(CashMovement.id)
        .filter(
            CashMovement.business_id == business_id,
            CashMovement.kind == "opening",
            CashMovement.date <= ref_date,
        )
        .first()
        is not None
    )

    return {
        "currency": business.currency,
        "as_of": ref_date,
        "cash_on_hand": q4(Decimal(raw_cash)),
        "min_cash_reserve": q4(Decimal(business.min_cash_reserve)),
        "opening_cash_set": opening_exists,
        "incomplete_data": not opening_exists,
    }


def get_open_transaction_balances(
    db: Session,
    business_id: uuid.UUID,
    tx_types: tuple[str, ...],
    as_of: dt.date | None = None,
) -> list[OpenTransactionBalance]:
    """Return open transaction balances up to as_of (overdue iff due_date <= as_of).

    Payments count only CashMovement rows with ``kind == 'payment'`` linked directly
    to the original transaction; refund movements link to the return transaction and
    never distort original sale/purchase balances. Per-transaction clamping prevents
    a return exceeding the unpaid balance from producing negative receivables/payables.
    """
    ref_date = _resolve_as_of(as_of)

    pay_subq = (
        db.query(
            CashMovement.transaction_id.label("tx_id"),
            func.coalesce(func.sum(CashMovement.signed_amount), ZERO).label("net_payment"),
        )
        .filter(
            CashMovement.business_id == business_id,
            CashMovement.kind == "payment",
            CashMovement.transaction_id.is_not(None),
            CashMovement.date <= ref_date,
        )
        .group_by(CashMovement.transaction_id)
        .subquery()
    )

    ret_subq = (
        db.query(
            Transaction.original_transaction_id.label("orig_id"),
            func.coalesce(func.sum(Transaction.total), ZERO).label("returns_total"),
        )
        .filter(
            Transaction.business_id == business_id,
            Transaction.original_transaction_id.is_not(None),
            Transaction.status == "posted",
            Transaction.date <= ref_date,
        )
        .group_by(Transaction.original_transaction_id)
        .subquery()
    )

    rows = (
        db.query(
            Transaction,
            Customer.name.label("customer_name"),
            Supplier.name.label("supplier_name"),
            func.coalesce(pay_subq.c.net_payment, ZERO).label("net_payment"),
            func.coalesce(ret_subq.c.returns_total, ZERO).label("returns_total"),
        )
        .outerjoin(Customer, Customer.id == Transaction.customer_id)
        .outerjoin(Supplier, Supplier.id == Transaction.supplier_id)
        .outerjoin(pay_subq, pay_subq.c.tx_id == Transaction.id)
        .outerjoin(ret_subq, ret_subq.c.orig_id == Transaction.id)
        .filter(
            Transaction.business_id == business_id,
            Transaction.status == "posted",
            Transaction.type.in_(tx_types),
            Transaction.date <= ref_date,
        )
        .order_by(Transaction.due_date.asc().nulls_last(), Transaction.date.asc())
        .all()
    )

    open_items: list[OpenTransactionBalance] = []
    for tx, cust_name, sup_name, raw_net_payment, raw_returns in rows:
        net_payment = Decimal(raw_net_payment)
        amount_paid = net_payment if tx.type == "sale" else -net_payment
        returns_total = Decimal(raw_returns)
        raw_balance = Decimal(tx.total) - returns_total - amount_paid
        if raw_balance <= Decimal("0"):
            continue
        balance_due = q4(raw_balance)
        party_id = tx.customer_id if tx.type == "sale" else tx.supplier_id
        party_name = cust_name if tx.type == "sale" else sup_name
        overdue = tx.due_date is not None and tx.due_date <= ref_date
        open_items.append(
            OpenTransactionBalance(
                transaction_id=tx.id,
                tx_type=tx.type,
                party_id=party_id,
                party_name=party_name,
                date=tx.date,
                due_date=tx.due_date,
                total=q4(Decimal(tx.total)),
                amount_paid=q4(amount_paid),
                returns_total=q4(returns_total),
                balance_due=balance_due,
                overdue=overdue,
            )
        )
    return open_items


def _summarize_dues(open_items: list[OpenTransactionBalance]) -> dict[str, object]:
    total = Decimal("0")
    overdue_total = Decimal("0")
    overdue_count = 0
    by_party: dict[tuple[uuid.UUID | None, str], dict[str, object]] = {}

    for item in open_items:
        total += item.balance_due
        if item.overdue:
            overdue_total += item.balance_due
            overdue_count += 1

        party_label = item.party_name or "Unassigned"
        key = (item.party_id, party_label)
        if key not in by_party:
            by_party[key] = {
                "party_id": str(item.party_id) if item.party_id else None,
                "party_name": party_label,
                "balance_due": Decimal("0"),
                "overdue_amount": Decimal("0"),
                "earliest_due_date": item.due_date,
            }
        entry = by_party[key]
        entry["balance_due"] = Decimal(entry["balance_due"]) + item.balance_due
        if item.overdue:
            entry["overdue_amount"] = Decimal(entry["overdue_amount"]) + item.balance_due
        existing_due = entry["earliest_due_date"]
        if item.due_date is not None and (
            existing_due is None or item.due_date < existing_due
        ):
            entry["earliest_due_date"] = item.due_date

    parties_sorted = sorted(
        by_party.values(),
        key=lambda p: Decimal(p["balance_due"]),
        reverse=True,
    )
    for entry in parties_sorted:
        entry["balance_due"] = q4(Decimal(entry["balance_due"]))
        entry["overdue_amount"] = q4(Decimal(entry["overdue_amount"]))

    return {
        "total": q4(total),
        "overdue_amount": q4(overdue_total),
        "not_due_amount": q4(total - overdue_total),
        "overdue_count": overdue_count,
        "parties": parties_sorted,
        "open_transactions": open_items,
    }


def get_receivables(
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date | None = None,
) -> dict[str, object]:
    """Summarize open customer receivables up to as_of (overdue iff due_date <= as_of)."""
    open_items = get_open_transaction_balances(db, business_id, ("sale",), as_of=as_of)
    return _summarize_dues(open_items)


def get_payables(
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date | None = None,
) -> dict[str, object]:
    """Summarize open supplier/expense payables up to as_of (overdue iff due_date <= as_of)."""
    open_items = get_open_transaction_balances(
        db, business_id, ("purchase", "expense"), as_of=as_of
    )
    return _summarize_dues(open_items)


def get_data_coverage(
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date | None = None,
) -> dict[str, object]:
    """Measure available historical span and record completeness up to as_of."""
    ref_date = _resolve_as_of(as_of)

    min_cash_date = db.query(func.min(CashMovement.date)).filter(
        CashMovement.business_id == business_id,
        CashMovement.date <= ref_date,
    ).scalar()
    min_tx_date = db.query(func.min(Transaction.date)).filter(
        Transaction.business_id == business_id,
        Transaction.status == "posted",
        Transaction.date <= ref_date,
    ).scalar()
    min_inv_date = db.query(func.min(InventoryMovement.date)).filter(
        InventoryMovement.business_id == business_id,
        InventoryMovement.date <= ref_date,
    ).scalar()

    dates = [d for d in (min_cash_date, min_tx_date, min_inv_date) if d is not None]
    earliest_date = min(dates) if dates else None
    history_days = ((ref_date - earliest_date).days + 1) if earliest_date is not None else 0

    cash_pos = get_cash_position(db, business_id, as_of=ref_date)
    missing_due_count = (
        db.query(func.count(Transaction.id))
        .filter(
            Transaction.business_id == business_id,
            Transaction.status == "posted",
            Transaction.type.in_(["sale", "purchase"]),
            Transaction.date <= ref_date,
            Transaction.due_date.is_(None),
        )
        .scalar()
        or 0
    )

    return {
        "as_of": ref_date,
        "earliest_date": earliest_date,
        "history_days": history_days,
        "limited_data": history_days < 14,
        "opening_cash_set": cash_pos["opening_cash_set"],
        "incomplete_data": cash_pos["incomplete_data"],
        "tx_missing_due_date": int(missing_due_count),
    }


def get_inventory_insights(
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date | None = None,
    new_stock_grace_days: int = NEW_STOCK_GRACE_DAYS,
) -> InventoryResponse:
    """Compute stock on hand, stock value, velocity, days of stock, and slow-stock capital."""
    ref_date = _resolve_as_of(as_of)
    business = db.get(Business, business_id)
    assert business is not None

    coverage = get_data_coverage(db, business_id, as_of=ref_date)
    history_days = int(coverage["history_days"])
    velocity_window_days = max(1, min(30, history_days))
    window_start = ref_date - dt.timedelta(days=velocity_window_days - 1)

    products = (
        db.query(Product)
        .filter(Product.business_id == business_id)
        .order_by(Product.name.asc())
        .all()
    )

    inv_rows = (
        db.query(
            InventoryMovement.product_id,
            func.coalesce(func.sum(InventoryMovement.qty_delta), ZERO).label("on_hand"),
            func.min(
                case(
                    (
                        InventoryMovement.type.in_(["opening", "purchase"]),
                        InventoryMovement.date,
                    ),
                    else_=None,
                )
            ).label("first_received"),
        )
        .filter(
            InventoryMovement.business_id == business_id,
            InventoryMovement.date <= ref_date,
        )
        .group_by(InventoryMovement.product_id)
        .all()
    )
    on_hand_by_pid: dict[uuid.UUID, Decimal] = {}
    first_received_by_pid: dict[uuid.UUID, dt.date | None] = {}
    for pid, on_hand, first_rec in inv_rows:
        on_hand_by_pid[pid] = Decimal(on_hand)
        first_received_by_pid[pid] = first_rec

    sales_rows = (
        db.query(
            TransactionItem.product_id,
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.type == "sale", TransactionItem.qty),
                        else_=-TransactionItem.qty,
                    )
                ),
                ZERO,
            ).label("net_qty"),
        )
        .join(Transaction, Transaction.id == TransactionItem.transaction_id)
        .filter(
            Transaction.business_id == business_id,
            Transaction.status == "posted",
            Transaction.type.in_(["sale", "sale_return"]),
            Transaction.date >= window_start,
            Transaction.date <= ref_date,
            TransactionItem.product_id.is_not(None),
        )
        .group_by(TransactionItem.product_id)
        .all()
    )
    sold_by_pid: dict[uuid.UUID, Decimal] = {
        pid: max(Decimal("0"), Decimal(qty)) for pid, qty in sales_rows if pid is not None
    }

    total_stock_raw = Decimal("0")
    slow_stock_raw = Decimal("0")
    items_out: list[InventoryItemOut] = []

    for prod in products:
        on_hand_raw = on_hand_by_pid.get(prod.id, Decimal("0"))
        avg_cost_raw = Decimal(prod.avg_cost)
        stock_value_raw = (on_hand_raw * avg_cost_raw) if prod.track_inventory else Decimal("0")
        if prod.track_inventory and on_hand_raw > Decimal("0"):
            total_stock_raw += stock_value_raw

        sold_raw = sold_by_pid.get(prod.id, Decimal("0"))
        velocity_raw = sold_raw / Decimal(velocity_window_days)
        days_of_stock_raw = (on_hand_raw / velocity_raw) if velocity_raw > Decimal("0") else None

        first_rec = first_received_by_pid.get(prod.id)
        is_fresh = (
            first_rec is not None and (ref_date - first_rec).days < new_stock_grace_days
        )
        slow_stock = False
        if prod.track_inventory and on_hand_raw > Decimal("0") and not is_fresh:
            if velocity_raw == Decimal("0"):
                slow_stock = True
            elif (
                days_of_stock_raw is not None
                and days_of_stock_raw >= Decimal(business.slow_stock_days_threshold)
            ):
                slow_stock = True

        if slow_stock:
            slow_stock_raw += stock_value_raw

        low_stock = prod.track_inventory and on_hand_raw <= Decimal(prod.reorder_level)
        items_out.append(
            InventoryItemOut(
                product_id=prod.id,
                name=prod.name,
                sku=prod.sku,
                unit=prod.unit,
                track_inventory=prod.track_inventory,
                on_hand_qty=q4(on_hand_raw),
                avg_cost=q4(avg_cost_raw),
                stock_value=q4(stock_value_raw),
                sale_price=q4(Decimal(prod.sale_price)),
                reorder_level=q4(Decimal(prod.reorder_level)),
                units_sold_window=q4(sold_raw),
                daily_velocity=q4(velocity_raw),
                days_of_stock=q4(days_of_stock_raw) if days_of_stock_raw is not None else None,
                slow_stock=slow_stock,
                low_stock=low_stock,
                first_received_date=first_rec,
            )
        )

    slow_pct_raw = (
        (slow_stock_raw / total_stock_raw * Decimal("100"))
        if total_stock_raw > Decimal("0")
        else Decimal("0")
    )

    return InventoryResponse(
        currency=business.currency,
        as_of=ref_date,
        velocity_window_days=velocity_window_days,
        slow_stock_days_threshold=business.slow_stock_days_threshold,
        total_stock_value=q4(total_stock_raw),
        slow_stock_value_flagged=q4(slow_stock_raw),
        slow_stock_pct_of_inventory=q4(slow_pct_raw),
        items=items_out,
    )


def get_profitability(
    db: Session,
    business_id: uuid.UUID,
    days: int = 30,
    as_of: dt.date | None = None,
) -> ProfitabilityResponse:
    """Compute net sales, COGS, gross profit/margin, expenses, and per-product margins.

    Purchases are excluded from expenses; inventory cost hits P&L only when sold
    through ``TransactionItem.unit_cost_snapshot``.
    """
    ref_date = _resolve_as_of(as_of)
    business = db.get(Business, business_id)
    assert business is not None
    window_start = ref_date - dt.timedelta(days=days - 1)

    tx_rows = (
        db.query(Transaction)
        .filter(
            Transaction.business_id == business_id,
            Transaction.status == "posted",
            Transaction.type.in_(["sale", "sale_return", "expense"]),
            Transaction.date >= window_start,
            Transaction.date <= ref_date,
        )
        .all()
    )

    discounts_raw = Decimal("0")
    returns_raw = Decimal("0")
    expenses_raw = Decimal("0")
    sale_tx_ids: list[uuid.UUID] = []
    return_tx_ids: list[uuid.UUID] = []
    tx_discount_by_id: dict[uuid.UUID, Decimal] = {}

    for tx in tx_rows:
        if tx.type == "sale":
            sale_tx_ids.append(tx.id)
            discounts_raw += Decimal(tx.discount)
            tx_discount_by_id[tx.id] = Decimal(tx.discount)
        elif tx.type == "sale_return":
            return_tx_ids.append(tx.id)
            returns_raw += Decimal(tx.total)
        elif tx.type == "expense":
            expenses_raw += Decimal(tx.total)

    relevant_tx_ids = sale_tx_ids + return_tx_ids
    item_rows = (
        db.query(TransactionItem, Transaction.type, Product.name, Product.sku)
        .join(Transaction, Transaction.id == TransactionItem.transaction_id)
        .outerjoin(Product, Product.id == TransactionItem.product_id)
        .filter(TransactionItem.transaction_id.in_(relevant_tx_ids))
        .all()
        if relevant_tx_ids
        else []
    )

    sale_subtotal_by_tx: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for item, tx_type, _, _ in item_rows:
        if tx_type == "sale":
            sale_subtotal_by_tx[item.transaction_id] += Decimal(item.qty) * Decimal(item.unit_price)

    gross_sales_raw = Decimal("0")
    cogs_raw = Decimal("0")
    prod_acc: dict[uuid.UUID, dict[str, object]] = {}

    for item, tx_type, prod_name, prod_sku in item_rows:
        line_rev = Decimal(item.qty) * Decimal(item.unit_price)
        line_cost = Decimal(item.qty) * Decimal(item.unit_cost_snapshot)

        if tx_type == "sale":
            gross_sales_raw += line_rev
            cogs_raw += line_cost
            tx_sub = sale_subtotal_by_tx.get(item.transaction_id, Decimal("0"))
            tx_disc = tx_discount_by_id.get(item.transaction_id, Decimal("0"))
            net_line_rev = (
                line_rev * (Decimal("1") - (tx_disc / tx_sub))
                if tx_sub > Decimal("0") and tx_disc > Decimal("0")
                else line_rev
            )
            qty_signed = Decimal(item.qty)
            cost_signed = line_cost
        else:
            cogs_raw -= line_cost
            net_line_rev = -line_rev
            qty_signed = -Decimal(item.qty)
            cost_signed = -line_cost

        if item.product_id is not None:
            if item.product_id not in prod_acc:
                prod_acc[item.product_id] = {
                    "product_id": item.product_id,
                    "name": prod_name or "",
                    "sku": prod_sku or "",
                    "qty_sold": Decimal("0"),
                    "net_sales": Decimal("0"),
                    "cogs": Decimal("0"),
                }
            acc = prod_acc[item.product_id]
            acc["qty_sold"] = Decimal(acc["qty_sold"]) + qty_signed
            acc["net_sales"] = Decimal(acc["net_sales"]) + net_line_rev
            acc["cogs"] = Decimal(acc["cogs"]) + cost_signed

    net_sales_raw = gross_sales_raw - discounts_raw - returns_raw
    gross_profit_raw = net_sales_raw - cogs_raw
    gross_margin_raw = (
        (gross_profit_raw / net_sales_raw * Decimal("100"))
        if net_sales_raw > Decimal("0")
        else Decimal("0")
    )
    net_operating_profit_raw = gross_profit_raw - expenses_raw

    products_out: list[ProductMarginOut] = []
    for acc in sorted(
        prod_acc.values(),
        key=lambda p: Decimal(p["net_sales"]),
        reverse=True,
    ):
        p_net = Decimal(acc["net_sales"])
        p_cogs = Decimal(acc["cogs"])
        p_gp = p_net - p_cogs
        p_margin = (p_gp / p_net * Decimal("100")) if p_net > Decimal("0") else Decimal("0")
        products_out.append(
            ProductMarginOut(
                product_id=acc["product_id"],
                name=str(acc["name"]),
                sku=str(acc["sku"]),
                qty_sold=q4(Decimal(acc["qty_sold"])),
                net_sales=q4(p_net),
                cogs=q4(p_cogs),
                gross_profit=q4(p_gp),
                gross_margin_pct=q4(p_margin),
            )
        )

    return ProfitabilityResponse(
        currency=business.currency,
        as_of=ref_date,
        period_days=days,
        gross_sales=q4(gross_sales_raw),
        discounts=q4(discounts_raw),
        returns=q4(returns_raw),
        net_sales=q4(net_sales_raw),
        cogs=q4(cogs_raw),
        gross_profit=q4(gross_profit_raw),
        gross_margin_pct=q4(gross_margin_raw),
        expenses=q4(expenses_raw),
        net_operating_profit=q4(net_operating_profit_raw),
        products=products_out,
    )
