import datetime as dt
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_business_id
from app.db import get_db
from app.schemas import (
    CashMovementOut,
    InventoryMovementOut,
    OpeningCashCreate,
    OpeningStockCreate,
    PaymentCreate,
    TransactionCreate,
    TransactionOut,
)
from app.services import ledger

router = APIRouter(tags=["ledger"])


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions_endpoint(
    type: Literal["sale", "purchase", "expense", "sale_return", "purchase_return"] | None = None,
    customer_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    unpaid_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> list[TransactionOut]:
    """List transactions for the authenticated business with computed balances."""
    return ledger.list_transactions(
        db=db,
        business_id=business_id,
        tx_type=type,
        customer_id=customer_id,
        supplier_id=supplier_id,
        date_from=date_from,
        date_to=date_to,
        unpaid_only=unpaid_only,
        limit=limit,
        offset=offset,
    )


@router.post("/transactions", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_transaction_endpoint(
    payload: TransactionCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> TransactionOut:
    """Create and post a transaction in a single database transaction."""
    try:
        result = ledger.create_transaction(db=db, business_id=business_id, payload=payload)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.post(
    "/transactions/{transaction_id}/payments",
    response_model=CashMovementOut,
    status_code=status.HTTP_201_CREATED,
)
def record_payment_endpoint(
    transaction_id: uuid.UUID,
    payload: PaymentCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> CashMovementOut:
    """Record an idempotent partial or full payment against an open transaction."""
    try:
        result = ledger.record_payment(
            db=db,
            business_id=business_id,
            transaction_id=transaction_id,
            payload=payload,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.post("/cash/opening", response_model=CashMovementOut)
def set_opening_cash_endpoint(
    payload: OpeningCashCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> CashMovementOut:
    """Set or update opening cash for the authenticated business."""
    try:
        result = ledger.set_opening_cash(db=db, business_id=business_id, payload=payload)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@router.post(
    "/inventory/opening",
    response_model=InventoryMovementOut,
    status_code=status.HTTP_201_CREATED,
)
def set_opening_stock_endpoint(
    payload: OpeningStockCreate,
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> InventoryMovementOut:
    """Record opening stock quantity and unit cost for a tracked product."""
    try:
        result = ledger.set_opening_stock(db=db, business_id=business_id, payload=payload)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
