"""Deterministic scenario runner built on top of forecast.build_forecast."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import ScheduledEvent
from app.schemas import ScenarioImpactOut, ScenarioRequest, ScenarioResponse
from app.services import finance, forecast
from app.services.finance import ZERO, q4
from app.services.forecast import (
    ExtraOutflowOverride,
    ForecastOverride,
    MoveInflowOverride,
    MoveOutflowOverride,
    ReduceOutflowOverride,
)


def run_scenario(
    db: Session,
    business_id: uuid.UUID,
    req: ScenarioRequest,
    as_of: dt.date | None = None,
) -> ScenarioResponse:
    """Run one what-if scenario against baseline without modifying any ledger rows."""
    ref_date = as_of or dt.date.today()
    horizon_end = ref_date + dt.timedelta(days=req.horizon_days)

    baseline = forecast.build_forecast(db, business_id, days=req.horizon_days, as_of=ref_date)
    receivables = finance.get_receivables(db, business_id, as_of=ref_date)
    inventory = finance.get_inventory_insights(db, business_id, as_of=ref_date)
    trapped_capital = q4(
        Decimal(receivables["overdue_amount"]) + inventory.slow_stock_value_flagged  # type: ignore[arg-type]
    )

    overrides: list[ForecastOverride] = []

    if req.type == "collect_dues":
        pct = req.collect_pct if req.collect_pct is not None else Decimal("50")
        collect_on = ref_date + dt.timedelta(days=2)
        overdue_sales = [
            tx
            for tx in receivables["open_transactions"]  # type: ignore[attr-defined]
            if tx.overdue
        ]
        if req.transaction_id is not None:
            matched = [tx for tx in overdue_sales if tx.transaction_id == req.transaction_id]
            if not matched:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Target overdue receivable not found in this business",
                )
            overdue_sales = matched
        for tx in overdue_sales:
            amt = q4(tx.balance_due * pct / Decimal("100"))
            if amt > ZERO:
                overrides.append(
                    MoveInflowOverride(
                        transaction_id=tx.transaction_id,
                        new_date=collect_on,
                        amount=amt,
                    )
                )

    elif req.type == "delay_payment":
        delay_days = req.delay_days if req.delay_days is not None else 7
        payables = finance.get_payables(db, business_id, as_of=ref_date)
        open_payables = list(payables["open_transactions"])  # type: ignore[arg-defined]
        if req.transaction_id is not None:
            matched = [tx for tx in open_payables if tx.transaction_id == req.transaction_id]
            if not matched:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Target payable transaction not found in this business",
                )
            target_tx = matched[0]
        else:
            in_horizon = [
                tx
                for tx in open_payables
                if tx.due_date is None or tx.due_date <= horizon_end
            ]
            candidates = in_horizon or open_payables
            if not candidates:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No open supplier payable found to delay",
                )
            target_tx = max(candidates, key=lambda t: t.balance_due)
        overrides.append(
            MoveOutflowOverride(
                transaction_id=target_tx.transaction_id,
                delay_days=delay_days,
            )
        )

    elif req.type == "reorder_less":
        pct = req.reorder_reduction_pct if req.reorder_reduction_pct is not None else Decimal("50")
        if req.scheduled_event_id is not None:
            ev = (
                db.query(ScheduledEvent)
                .filter(
                    ScheduledEvent.id == req.scheduled_event_id,
                    ScheduledEvent.business_id == business_id,
                    ScheduledEvent.status == "active",
                    ScheduledEvent.direction == "outflow",
                )
                .first()
            )
            if ev is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Planned reorder event not found in this business",
                )
            overrides.append(
                ReduceOutflowOverride(scheduled_event_id=ev.id, reduction_pct=pct)
            )
        elif req.transaction_id is not None:
            payables = finance.get_payables(db, business_id, as_of=ref_date)
            matched = [
                tx
                for tx in payables["open_transactions"]  # type: ignore[attr-defined]
                if tx.transaction_id == req.transaction_id
            ]
            if not matched:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Target purchase payable not found in this business",
                )
            overrides.append(
                ReduceOutflowOverride(transaction_id=matched[0].transaction_id, reduction_pct=pct)
            )
        else:
            # Prefer an active scheduled outflow event inside the horizon, else largest open purchase
            ev = (
                db.query(ScheduledEvent)
                .filter(
                    ScheduledEvent.business_id == business_id,
                    ScheduledEvent.status == "active",
                    ScheduledEvent.direction == "outflow",
                    ScheduledEvent.expected_on <= horizon_end,
                )
                .order_by(ScheduledEvent.amount.desc())
                .first()
            )
            if ev is not None:
                overrides.append(
                    ReduceOutflowOverride(scheduled_event_id=ev.id, reduction_pct=pct)
                )
            else:
                payables = finance.get_payables(db, business_id, as_of=ref_date)
                purchases = [
                    tx
                    for tx in payables["open_transactions"]  # type: ignore[attr-defined]
                    if tx.tx_type == "purchase"
                ]
                if not purchases:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="No planned reorder or open purchase found to reduce",
                    )
                target_tx = max(purchases, key=lambda t: t.balance_due)
                overrides.append(
                    ReduceOutflowOverride(
                        transaction_id=target_tx.transaction_id,
                        reduction_pct=pct,
                    )
                )

    elif req.type == "planned_purchase":
        if req.planned_purchase_amount is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="planned_purchase_amount is required for planned_purchase scenario",
            )
        purchase_date = req.planned_purchase_date or (ref_date + dt.timedelta(days=3))
        if purchase_date <= ref_date or purchase_date > horizon_end:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"planned_purchase_date must be between {ref_date + dt.timedelta(days=1)} and {horizon_end}",
            )
        overrides.append(
            ExtraOutflowOverride(
                label="Planned purchase",
                amount=q4(req.planned_purchase_amount),
                on=purchase_date,
            )
        )

    simulated = forecast.build_forecast(
        db,
        business_id,
        days=req.horizon_days,
        as_of=ref_date,
        overrides=overrides,
    )

    baseline_breach_days = sum(1 for d in baseline.daily if d.below_reserve)
    sim_breach_days = sum(1 for d in simulated.daily if d.below_reserve)

    affordable: bool | None = None
    if req.type == "planned_purchase":
        affordable = simulated.lowest_cash_amount >= simulated.min_cash_reserve

    impact = ScenarioImpactOut(
        projected_cash_improvement=q4(
            simulated.lowest_cash_amount - baseline.lowest_cash_amount
        ),
        gap_reduction_vs_reserve=q4(
            baseline.estimated_cash_gap_vs_reserve - simulated.estimated_cash_gap_vs_reserve
        ),
        reserve_breach_days_avoided=baseline_breach_days - sim_breach_days,
        trapped_internal_capital=trapped_capital,
        affordable_above_reserve=affordable,
    )

    return ScenarioResponse(
        currency=baseline.currency,
        scenario_type=req.type,
        baseline=baseline,
        simulated=simulated,
        impact=impact,
    )
