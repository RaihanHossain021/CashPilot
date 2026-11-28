import datetime as dt
import uuid
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_business_id
from app.db import get_db
from app.schemas import ForecastResponse, InventoryResponse, ProfitabilityResponse
from app.services import finance, forecast

router = APIRouter(tags=["reports"])


@router.get("/inventory", response_model=InventoryResponse)
def get_inventory_endpoint(
    as_of: dt.date | None = Query(default=None),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> InventoryResponse:
    """Return stock on hand, valuation, velocity, days of stock, and slow-stock flags."""
    return finance.get_inventory_insights(db, business_id, as_of=as_of)


@router.get("/profitability", response_model=ProfitabilityResponse)
def get_profitability_endpoint(
    days: int = Query(default=30, ge=1, le=365),
    as_of: dt.date | None = Query(default=None),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> ProfitabilityResponse:
    """Return net sales, COGS, gross profit, margin %, expenses, and per-product margins."""
    return finance.get_profitability(db, business_id, days=days, as_of=as_of)


@router.get("/cashflow/forecast", response_model=ForecastResponse)
def get_cashflow_forecast_endpoint(
    days: int = Query(default=14),
    as_of: dt.date | None = Query(default=None),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> ForecastResponse:
    """Return 7, 14, or 30-day cash-flow projection, estimated cash gap, and causes."""
    if days not in (7, 14, 30):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="days must be one of 7, 14, or 30",
        )
    return forecast.build_forecast(
        db, business_id, days=cast(Literal[7, 14, 30], days), as_of=as_of
    )
