"""Internal-capital-first rule-based recommendations (Phase 9)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from app.models import ScheduledEvent, Transaction
from app.schemas import (
    ForecastResponse,
    InventoryResponse,
    RecommendationOut,
    RecommendationsResponse,
    ScenarioRequest,
)
from app.services import finance, forecast, scenario
from app.services.finance import ZERO, q4

MAX_RECOMMENDATIONS = 5


def build_recommendations(
    db: Session,
    business_id: uuid.UUID,
    currency: str,
    receivables: dict[str, object],
    inventory: InventoryResponse,
    coverage: dict[str, object],
    fc: ForecastResponse,
    as_of: dt.date,
) -> list[RecommendationOut]:
    """Generate deterministic, ranked, contract-valid recommendations."""
    limited_note = (
        f" Limited data ({fc.history_days} days history < 14); baseline estimates are provisional."
        if fc.limited_data
        else ""
    )

    # 1. Incomplete data must take precedence over unreliable gap recommendations.
    if bool(coverage["incomplete_data"]):
        return [
            RecommendationOut(
                id="SET_OPENING_CASH:global",
                priority=1,
                code="SET_OPENING_CASH",
                title="Set your opening cash balance first",
                issue="Opening cash is missing, so cash-on-hand and forecast gap figures are incomplete.",
                evidence="No opening cash movement recorded in the ledger.",
                suggested_action="Open Ledger and record your starting cash balance.",
                estimated_impact="not quantifiable",
                limitations="Forecasts and gap recommendations stay disabled until opening cash is set.",
                suggested_scenario=None,
            )
        ]

    gap_vs_reserve = fc.estimated_cash_gap_vs_reserve
    gap_vs_zero = fc.estimated_cash_gap_vs_zero

    # 2. No gap -> empty list ("no action needed" state, no filler).
    if gap_vs_reserve <= ZERO:
        return []

    overdue_amt = Decimal(receivables["overdue_amount"])  # type: ignore[arg-type]
    slow_value = inventory.slow_stock_value_flagged
    trapped_capital = q4(overdue_amt + slow_value)

    if trapped_capital >= gap_vs_reserve:
        coverage_context = (
            f"Up to {trapped_capital} {currency} is tied up in overdue dues and slow stock, "
            f"which could cover the {gap_vs_reserve} {currency} reserve gap internally if realized."
        )
    else:
        shortfall = q4(gap_vs_reserve - trapped_capital)
        coverage_context = (
            f"Up to {trapped_capital} {currency} is tied up internally, leaving a remaining "
            f"shortfall of {shortfall} {currency} against the {gap_vs_reserve} {currency} reserve gap."
        )

    horizon: Literal[14, 30] = 30 if fc.horizon_days == 30 else 14
    horizon_end = as_of + dt.timedelta(days=horizon)
    candidates: list[tuple[int, Decimal, RecommendationOut]] = []

    # 3. Collect overdue customer dues first
    if overdue_amt > ZERO:
        overdue_parties = [
            f"{p['party_name']} ({p['overdue_amount']} {currency})"
            for p in receivables["parties"]  # type: ignore[index]
            if Decimal(p["overdue_amount"]) > ZERO
        ][:3]
        party_list = ", ".join(overdue_parties) if overdue_parties else "overdue customers"
        collect_req = ScenarioRequest(
            type="collect_dues",
            horizon_days=horizon,
            collect_pct=Decimal("50"),
        )
        sc_res = scenario.run_scenario(db, business_id, collect_req, as_of=as_of)
        impact_amt = sc_res.impact.cash_impact
        candidates.append(
            (
                1,
                impact_amt,
                RecommendationOut(
                    id="COLLECT_OVERDUE_DUES:all",
                    priority=1,
                    code="COLLECT_OVERDUE_DUES",
                    title="Collect overdue customer dues first",
                    issue=f"Up to {overdue_amt} {currency} is tied up in {receivables['overdue_count']} overdue invoices.",
                    evidence=f"Overdue balances: {party_list}. {coverage_context}",
                    suggested_action="Follow up on overdue invoices or offer an early-settlement prompt.",
                    estimated_impact=(
                        f"Collecting 50% improves lowest projected cash by +{impact_amt} {currency} "
                        f"(reduces reserve gap by {sc_res.impact.gap_reduction_vs_reserve} {currency})."
                    ),
                    limitations=(
                        "Assumes customers settle balances within the forecast window; "
                        f"uncollected dues are not cash yet.{limited_note}"
                    ),
                    suggested_scenario=collect_req,
                ),
            )
        )

    # 4. Slow-moving stock tied-up capital
    if slow_value > ZERO:
        slow_items = sorted(
            [item for item in inventory.items if item.slow_stock],
            key=lambda i: i.stock_value,
            reverse=True,
        )
        top_slow_names = ", ".join(item.name for item in slow_items[:2]) or "slow items"
        top_slow_evidence = ", ".join(
            f"{item.name} ({item.stock_value} {currency})" for item in slow_items[:3]
        )

        reorder_ev = (
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
        if reorder_ev is not None:
            reorder_req = ScenarioRequest(
                type="reorder_less",
                horizon_days=horizon,
                scheduled_event_id=reorder_ev.id,
                reorder_reduction_pct=Decimal("50"),
            )
            sc_reorder = scenario.run_scenario(db, business_id, reorder_req, as_of=as_of)
            reorder_impact = sc_reorder.impact.cash_impact
            rec_id = f"RELEASE_SLOW_STOCK:{reorder_ev.id}"
            title = "Trim planned reorders and clear slow-moving stock"
            impact_text = (
                f"Cutting '{reorder_ev.label}' by 50% saves {q4(reorder_ev.amount / Decimal('2'))} "
                f"{currency} (lowest-cash impact: +{reorder_impact} {currency})."
            )
            sort_val = reorder_impact
        else:
            reorder_req = None
            rec_id = "RELEASE_SLOW_STOCK:inventory"
            title = f"Review next reorder of {top_slow_names}"
            impact_text = "not quantifiable"
            sort_val = ZERO

        candidates.append(
            (
                2,
                sort_val,
                RecommendationOut(
                    id=rec_id,
                    priority=2,
                    code="RELEASE_SLOW_STOCK",
                    title=title,
                    issue=(
                        f"Up to {slow_value} {currency} ({inventory.slow_stock_pct_of_inventory}% of inventory) "
                        f"is tied up in slow-moving stock."
                    ),
                    evidence=f"Slow items flagged: {top_slow_evidence}. {coverage_context}",
                    suggested_action="Pause new reorders on slow SKUs and move stagnant stock via targeted promotions.",
                    estimated_impact=impact_text,
                    limitations=(
                        "Stock value is not cash until sold; liquidation speed depends on demand."
                        f"{limited_note}"
                    ),
                    suggested_scenario=reorder_req,
                ),
            )
        )

    # 5. Deduplicated large supplier payable inside the gap window
    cutoff = fc.lowest_cash_date
    seen_payable_ids: set[uuid.UUID] = set()
    for cause in fc.causes:
        if cause.kind != "outflow" or cause.record_id is None:
            continue
        if cause.due_on is not None and cause.due_on > cutoff:
            continue
        if cause.record_id in seen_payable_ids:
            continue
        tx = (
            db.query(Transaction)
            .filter(
                Transaction.id == cause.record_id,
                Transaction.business_id == business_id,
                Transaction.status == "posted",
                Transaction.type.in_(["purchase", "expense"]),
            )
            .first()
        )
        if tx is None:
            continue

        seen_payable_ids.add(tx.id)
        delay_req = ScenarioRequest(
            type="delay_payment",
            horizon_days=horizon,
            transaction_id=tx.id,
            delay_days=min(7, horizon),
        )
        sc_delay = scenario.run_scenario(db, business_id, delay_req, as_of=as_of)
        delay_impact = sc_delay.impact.cash_impact
        candidates.append(
            (
                3,
                delay_impact,
                RecommendationOut(
                    id=f"DELAY_LARGE_PAYABLE:{tx.id}",
                    priority=3,
                    code="DELAY_LARGE_PAYABLE",
                    title="Negotiate or stagger upcoming supplier payment",
                    issue=(
                        f"{cause.label} ({cause.amount} {currency}) on {cause.due_on} "
                        f"drives the cash gap ({gap_vs_zero} {currency} below zero, "
                        f"{gap_vs_reserve} {currency} below reserve)."
                    ),
                    evidence=f"Lowest projected balance hits {fc.lowest_cash_amount} {currency} on {fc.lowest_cash_date}.",
                    suggested_action="Request a 7-day extension or partial split payment with the supplier.",
                    estimated_impact=(
                        f"Deferring by 7 days improves lowest projected cash by +{delay_impact} {currency}"
                        + (" (payment moves outside this period)." if sc_delay.impact.moved_beyond_horizon else ".")
                    ),
                    limitations=f"Requires supplier agreement; shifts payment timing without reducing total owed.{limited_note}",
                    suggested_scenario=delay_req,
                ),
            )
        )
        break  # One primary payable card to avoid clutter/duplicates

    candidates.sort(key=lambda item: (item[0], -item[1], item[2].id))
    return [item[2] for item in candidates[:MAX_RECOMMENDATIONS]]


def get_recommendations_bundle(
    db: Session,
    business_id: uuid.UUID,
    days: Literal[14, 30] = 14,
    as_of: dt.date | None = None,
) -> RecommendationsResponse:
    """Shared single entry point for /recommendations and /dashboard."""
    ref_date = as_of or dt.date.today()
    cash_pos = finance.get_cash_position(db, business_id, as_of=ref_date)
    receivables = finance.get_receivables(db, business_id, as_of=ref_date)
    inventory = finance.get_inventory_insights(db, business_id, as_of=ref_date)
    coverage = finance.get_data_coverage(db, business_id, as_of=ref_date)
    fc = forecast.build_forecast(db, business_id, days=days, as_of=ref_date)
    currency = str(cash_pos["currency"])

    recs = build_recommendations(
        db=db,
        business_id=business_id,
        currency=currency,
        receivables=receivables,
        inventory=inventory,
        coverage=coverage,
        fc=fc,
        as_of=ref_date,
    )
    return RecommendationsResponse(
        currency=currency,
        as_of=ref_date,
        incomplete_data=bool(coverage["incomplete_data"]),
        limited_data=bool(fc.limited_data),
        recommendations=recs,
    )
