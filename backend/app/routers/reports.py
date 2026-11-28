import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_business_id
from app.db import get_db
from app.models import Business, Customer, Supplier
from app.schemas import (
    DashboardResponse,
    ForecastResponse,
    InventoryResponse,
    PartiesBalanceResponse,
    PartyBalanceOut,
    ProfitabilityResponse,
    ReadinessResponse,
    RecommendationsResponse,
)
from app.services import finance, forecast, readiness, recommend
from app.services.finance import ZERO, q4

router = APIRouter(tags=["reports"])


def _validate_alert_horizon(days: int) -> Literal[14, 30]:
    if days not in (14, 30):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Alert horizon must be 14 or 30 days so short-term shortages are not hidden",
        )
    return cast(Literal[14, 30], days)


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


@router.get("/readiness", response_model=ReadinessResponse)
def get_readiness_endpoint(
    days: int = Query(default=14),
    as_of: dt.date | None = Query(default=None),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> ReadinessResponse:
    """Return transparent green/amber/red financial-readiness profile with evidence."""
    horizon = _validate_alert_horizon(days)
    ref_date = as_of or dt.date.today()
    cash_pos = finance.get_cash_position(db, business_id, as_of=ref_date)
    receivables = finance.get_receivables(db, business_id, as_of=ref_date)
    inventory = finance.get_inventory_insights(db, business_id, as_of=ref_date)
    coverage = finance.get_data_coverage(db, business_id, as_of=ref_date)
    fc = forecast.build_forecast(db, business_id, days=horizon, as_of=ref_date)
    return readiness.evaluate_readiness(
        currency=str(cash_pos["currency"]),
        cash_position=cash_pos,
        receivables=receivables,
        inventory=inventory,
        coverage=coverage,
        forecast=fc,
    )


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard_endpoint(
    days: int = Query(default=14),
    as_of: dt.date | None = Query(default=None),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    """Return dashboard KPIs, cash gap summary, readiness profile, and recommendations."""
    horizon = _validate_alert_horizon(days)
    ref_date = as_of or dt.date.today()
    cash_pos = finance.get_cash_position(db, business_id, as_of=ref_date)
    receivables = finance.get_receivables(db, business_id, as_of=ref_date)
    payables = finance.get_payables(db, business_id, as_of=ref_date)
    inventory = finance.get_inventory_insights(db, business_id, as_of=ref_date)
    coverage = finance.get_data_coverage(db, business_id, as_of=ref_date)
    fc = forecast.build_forecast(db, business_id, days=horizon, as_of=ref_date)

    currency = str(cash_pos["currency"])
    readiness_summary = readiness.evaluate_readiness(
        currency=currency,
        cash_position=cash_pos,
        receivables=receivables,
        inventory=inventory,
        coverage=coverage,
        forecast=fc,
    )
    recs = recommend.build_recommendations(
        db=db,
        business_id=business_id,
        currency=currency,
        receivables=receivables,
        inventory=inventory,
        coverage=coverage,
        fc=fc,
        as_of=ref_date,
    )

    return DashboardResponse(
        currency=currency,
        period_days=30,
        cash_on_hand=Decimal(cash_pos["cash_on_hand"]),  # type: ignore[arg-type]
        min_cash_reserve=Decimal(cash_pos["min_cash_reserve"]),  # type: ignore[arg-type]
        customers_owe=Decimal(receivables["total"]),  # type: ignore[arg-type]
        overdue_receivables=Decimal(receivables["overdue_amount"]),  # type: ignore[arg-type]
        we_owe_suppliers=Decimal(payables["total"]),  # type: ignore[arg-type]
        total_stock_value=inventory.total_stock_value,
        slow_stock_value_flagged=inventory.slow_stock_value_flagged,
        slow_stock_pct_of_inventory=inventory.slow_stock_pct_of_inventory,
        estimated_cash_gap_vs_reserve=fc.estimated_cash_gap_vs_reserve,
        estimated_cash_gap_vs_zero=fc.estimated_cash_gap_vs_zero,
        gap_date=fc.lowest_cash_date if fc.estimated_cash_gap_vs_reserve > ZERO else None,
        incomplete_data=bool(cash_pos["incomplete_data"]),
        readiness_summary=readiness_summary,
        recommendations=recs,
    )


@router.get("/recommendations", response_model=RecommendationsResponse)
def get_recommendations_endpoint(
    days: int = Query(default=14),
    as_of: dt.date | None = Query(default=None),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> RecommendationsResponse:
    """Return deterministic, internal-capital-first recommendations (shared with /dashboard)."""
    horizon = _validate_alert_horizon(days)
    return recommend.get_recommendations_bundle(db, business_id, days=horizon, as_of=as_of)


@router.get("/parties/balances", response_model=PartiesBalanceResponse)
def get_parties_balances_endpoint(
    as_of: dt.date | None = Query(default=None),
    business_id: uuid.UUID = Depends(get_current_business_id),
    db: Session = Depends(get_db),
) -> PartiesBalanceResponse:
    """Return customers and suppliers with backend-computed open and overdue balances."""
    ref_date = as_of or dt.date.today()
    business = db.get(Business, business_id)
    assert business is not None

    rec_parties = {
        p["party_id"]: p
        for p in finance.get_receivables(db, business_id, as_of=ref_date)["parties"]  # type: ignore[index]
        if p["party_id"] is not None
    }
    pay_parties = {
        p["party_id"]: p
        for p in finance.get_payables(db, business_id, as_of=ref_date)["parties"]  # type: ignore[index]
        if p["party_id"] is not None
    }

    customers = (
        db.query(Customer)
        .filter(Customer.business_id == business_id)
        .order_by(Customer.name.asc())
        .all()
    )
    suppliers = (
        db.query(Supplier)
        .filter(Supplier.business_id == business_id)
        .order_by(Supplier.name.asc())
        .all()
    )

    customers_out = [
        PartyBalanceOut(
            id=c.id,
            kind="customer",
            name=c.name,
            phone=c.phone,
            balance_due=q4(Decimal(rec_parties[str(c.id)]["balance_due"]))
            if str(c.id) in rec_parties
            else ZERO,
            overdue_amount=q4(Decimal(rec_parties[str(c.id)]["overdue_amount"]))
            if str(c.id) in rec_parties
            else ZERO,
            earliest_due_date=rec_parties[str(c.id)]["earliest_due_date"]
            if str(c.id) in rec_parties
            else None,
        )
        for c in customers
    ]
    suppliers_out = [
        PartyBalanceOut(
            id=s.id,
            kind="supplier",
            name=s.name,
            phone=s.phone,
            balance_due=q4(Decimal(pay_parties[str(s.id)]["balance_due"]))
            if str(s.id) in pay_parties
            else ZERO,
            overdue_amount=q4(Decimal(pay_parties[str(s.id)]["overdue_amount"]))
            if str(s.id) in pay_parties
            else ZERO,
            earliest_due_date=pay_parties[str(s.id)]["earliest_due_date"]
            if str(s.id) in pay_parties
            else None,
        )
        for s in suppliers
    ]

    return PartiesBalanceResponse(
        currency=business.currency,
        as_of=ref_date,
        customers=customers_out,
        suppliers=suppliers_out,
    )
