"""Deterministic, strictly read-only scenario runner built on forecast.build_forecast."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import ScheduledEvent, Transaction
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


def _check_tx_target(
    db: Session,
    business_id: uuid.UUID,
    tx_id: uuid.UUID,
    allowed_types: tuple[str, ...],
    expected_label: str,
) -> Transaction:
    tx = (
        db.query(Transaction)
        .filter(Transaction.id == tx_id, Transaction.business_id == business_id)
        .first()
    )
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target transaction not found in this business",
        )
    if tx.status != "posted" or tx.type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Target transaction must be a posted {expected_label} (got '{tx.type}')",
        )
    return tx


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
    moved_beyond_horizon = False
    assumption_note = "Simulated projection."
    affordability_note: str | None = None

    if req.type == "collect_dues":
        pct = req.collect_pct if req.collect_pct is not None else Decimal("50")
        collect_on = ref_date + dt.timedelta(days=2)
        overdue_sales = [
            tx
            for tx in receivables["open_transactions"]  # type: ignore[attr-defined]
            if tx.overdue
        ]
        if req.transaction_id is not None:
            _check_tx_target(db, business_id, req.transaction_id, ("sale",), "sale")
            matched = [tx for tx in overdue_sales if tx.transaction_id == req.transaction_id]
            if not matched:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Target sale has no overdue balance due",
                )
            overdue_sales = matched
        elif not overdue_sales:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="No overdue customer dues available to collect",
            )

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
        assumption_note = f"Simulated: assumes customers pay {pct}% of overdue dues by {collect_on}."

    elif req.type == "delay_payment":
        delay_days = req.delay_days if req.delay_days is not None else 7
        payables = finance.get_payables(db, business_id, as_of=ref_date)
        open_payables = list(payables["open_transactions"])  # type: ignore[arg-defined]
        if req.transaction_id is not None:
            _check_tx_target(
                db, business_id, req.transaction_id, ("purchase", "expense"), "purchase or expense"
            )
            matched = [tx for tx in open_payables if tx.transaction_id == req.transaction_id]
            if not matched:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Target payable is already fully settled",
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
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="No open supplier payable available to delay",
                )
            target_tx = max(candidates, key=lambda t: t.balance_due)

        base_due = target_tx.due_date if target_tx.due_date is not None else (ref_date + dt.timedelta(days=1))
        shifted_due = base_due + dt.timedelta(days=delay_days)
        if shifted_due > horizon_end:
            moved_beyond_horizon = True

        overrides.append(
            MoveOutflowOverride(
                transaction_id=target_tx.transaction_id,
                delay_days=delay_days,
            )
        )
        assumption_note = (
            f"Simulated: assumes supplier agrees to defer payment by {delay_days} days."
            + (" Payment moves outside this period." if moved_beyond_horizon else "")
        )

    elif req.type == "reorder_less":
        pct = req.reorder_reduction_pct if req.reorder_reduction_pct is not None else Decimal("50")
        if req.scheduled_event_id is not None:
            ev = (
                db.query(ScheduledEvent)
                .filter(
                    ScheduledEvent.id == req.scheduled_event_id,
                    ScheduledEvent.business_id == business_id,
                )
                .first()
            )
            if ev is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Planned reorder event not found in this business",
                )
            if ev.status != "active" or ev.direction != "outflow":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Scheduled event must be an active outflow",
                )
            overrides.append(ReduceOutflowOverride(scheduled_event_id=ev.id, reduction_pct=pct))
        elif req.transaction_id is not None:
            _check_tx_target(db, business_id, req.transaction_id, ("purchase",), "purchase")
            payables = finance.get_payables(db, business_id, as_of=ref_date)
            matched = [
                tx
                for tx in payables["open_transactions"]  # type: ignore[attr-defined]
                if tx.transaction_id == req.transaction_id
            ]
            if not matched:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Target purchase has no remaining unpaid balance",
                )
            overrides.append(
                ReduceOutflowOverride(transaction_id=matched[0].transaction_id, reduction_pct=pct)
            )
        else:
            ev = (
                db.query(ScheduledEvent)
                .filter(
                    ScheduledEvent.business_id == business_id,
                    ScheduledEvent.status == "active",
                    ScheduledEvent.direction == "outflow",
                    ScheduledEvent.expected_on <= horizon_end,
                )
                .order_by(ScheduledEvent.amount.desc(), ScheduledEvent.id.asc())
                .first()
            )
            if ev is not None:
                overrides.append(ReduceOutflowOverride(scheduled_event_id=ev.id, reduction_pct=pct))
            else:
                payables = finance.get_payables(db, business_id, as_of=ref_date)
                purchases = [
                    tx
                    for tx in payables["open_transactions"]  # type: ignore[attr-defined]
                    if tx.tx_type == "purchase"
                ]
                if not purchases:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail="No planned reorder or open purchase found to reduce",
                    )
                target_tx = max(purchases, key=lambda t: t.balance_due)
                overrides.append(
                    ReduceOutflowOverride(
                        transaction_id=target_tx.transaction_id,
                        reduction_pct=pct,
                    )
                )
        assumption_note = f"Simulated: assumes planned reorder shrinks by {pct}% without causing stockouts."

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
        assumption_note = (
            f"Simulated: models a {q4(req.planned_purchase_amount)} {baseline.currency} outflow on {purchase_date}."
        )
        affordability_note = (
            "Cash coverage check only within this horizon (lowest closing cash >= reserve); "
            "does not judge whether the stock or purchase is needed."
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
        cash_impact=q4(simulated.lowest_cash_amount - baseline.lowest_cash_amount),
        gap_reduction_vs_reserve=q4(
            baseline.estimated_cash_gap_vs_reserve - simulated.estimated_cash_gap_vs_reserve
        ),
        breach_days_change=sim_breach_days - baseline_breach_days,
        trapped_internal_capital=trapped_capital,
        moved_beyond_horizon=moved_beyond_horizon,
        affordable_above_reserve=affordable,
        assumption_note=assumption_note,
        affordability_note=affordability_note,
    )

    return ScenarioResponse(
        currency=baseline.currency,
        scenario_type=req.type,
        baseline=baseline,
        simulated=simulated,
        impact=impact,
    )
