"""Read-only 7/14/30-day cash-flow forecast and cash-gap cause engine (Phase 5)."""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from app.models import Business, CashMovement, ScheduledEvent, Transaction
from app.schemas import CashGapCauseOut, ForecastDayOut, ForecastResponse
from app.services.finance import (
    ZERO,
    get_cash_position,
    get_data_coverage,
    get_inventory_insights,
    get_open_transaction_balances,
    q4,
)

MAX_HORIZON_DAYS = 30
ESTIMATE_WINDOW_DAYS = 14


@dataclass(frozen=True)
class MoveInflowOverride:
    """Move an open sale's expected inflow (or portion of it) to a simulated date."""

    transaction_id: uuid.UUID
    new_date: dt.date
    amount: Decimal


@dataclass(frozen=True)
class MoveOutflowOverride:
    """Delay an open payable's due date by delay_days."""

    transaction_id: uuid.UUID
    delay_days: int


@dataclass(frozen=True)
class ReduceOutflowOverride:
    """Reduce a payable's outflow amount by reduction_pct (0..100)."""

    transaction_id: uuid.UUID
    reduction_pct: Decimal


@dataclass(frozen=True)
class ExtraOutflowOverride:
    """Add a hypothetical planned purchase or outflow on a given date."""

    label: str
    amount: Decimal
    on: dt.date


ForecastOverride = (
    MoveInflowOverride | MoveOutflowOverride | ReduceOutflowOverride | ExtraOutflowOverride
)


def _compute_same_day_daily_estimates(
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date,
) -> tuple[Decimal, Decimal]:
    """Compute 14-day moving average of same-day operating inflows and outflows.

    Excludes opening cash and later settlements of prior credit transactions
    (where CashMovement.date != Transaction.date) so derived open balances are
    never double-counted with historical settlements. Each daily rate is
    quantized once at the end.
    """
    window_start = as_of - dt.timedelta(days=ESTIMATE_WINDOW_DAYS - 1)

    rows = (
        db.query(CashMovement, Transaction.date.label("tx_date"))
        .outerjoin(Transaction, Transaction.id == CashMovement.transaction_id)
        .filter(
            CashMovement.business_id == business_id,
            CashMovement.date >= window_start,
            CashMovement.date <= as_of,
            CashMovement.kind != "opening",
        )
        .all()
    )

    inflow_sum = Decimal("0")
    outflow_sum = Decimal("0")
    for move, tx_date in rows:
        if move.kind != "manual":
            if tx_date is None or move.date != tx_date:
                continue
        amt = Decimal(move.signed_amount)
        if amt > Decimal("0"):
            inflow_sum += amt
        elif amt < Decimal("0"):
            outflow_sum += -amt

    daily_inflow = q4(inflow_sum / Decimal(ESTIMATE_WINDOW_DAYS))
    daily_outflow = q4(outflow_sum / Decimal(ESTIMATE_WINDOW_DAYS))
    return daily_inflow, daily_outflow


def build_forecast(
    db: Session,
    business_id: uuid.UUID,
    days: Literal[7, 14, 30] = 14,
    as_of: dt.date | None = None,
    overrides: list[ForecastOverride] | None = None,
) -> ForecastResponse:
    """Build a deterministic 30-day cash-flow projection and slice it to ``days``.

    Read-only (never flushes or commits). Overdue payables (``due_date <= as_of``)
    and past-due active scheduled events land conservatively on day 1 (``as_of + 1``),
    while overdue customer receivables stay excluded from baseline inflows.
    """
    ref_date = as_of or dt.date.today()
    day_1 = ref_date + dt.timedelta(days=1)
    horizon_end_30 = ref_date + dt.timedelta(days=MAX_HORIZON_DAYS)

    business = db.get(Business, business_id)
    assert business is not None
    min_reserve = q4(Decimal(business.min_cash_reserve))

    cash_pos = get_cash_position(db, business_id, as_of=ref_date)
    starting_cash = Decimal(cash_pos["cash_on_hand"])
    coverage = get_data_coverage(db, business_id, as_of=ref_date)
    inventory = get_inventory_insights(db, business_id, as_of=ref_date)

    est_inflow, est_outflow = _compute_same_day_daily_estimates(db, business_id, ref_date)

    # Index overrides in memory without modifying DB state.
    inflow_moves_by_tx: dict[uuid.UUID, list[MoveInflowOverride]] = defaultdict(list)
    outflow_delays_by_tx: dict[uuid.UUID, int] = {}
    outflow_reductions_by_tx: dict[uuid.UUID, Decimal] = {}
    extra_outflows: list[ExtraOutflowOverride] = []

    for ov in overrides or []:
        if isinstance(ov, MoveInflowOverride):
            inflow_moves_by_tx[ov.transaction_id].append(ov)
        elif isinstance(ov, MoveOutflowOverride):
            outflow_delays_by_tx[ov.transaction_id] = (
                outflow_delays_by_tx.get(ov.transaction_id, 0) + ov.delay_days
            )
        elif isinstance(ov, ReduceOutflowOverride):
            outflow_reductions_by_tx[ov.transaction_id] = ov.reduction_pct
        elif isinstance(ov, ExtraOutflowOverride):
            extra_outflows.append(ov)

    confirmed_in: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))
    expected_in: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))
    confirmed_out: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))
    expected_out: dict[dt.date, Decimal] = defaultdict(lambda: Decimal("0"))

    outflow_causes: list[CashGapCauseOut] = []
    overdue_receivable_causes: list[CashGapCauseOut] = []

    # 1. Derived open payables -> confirmed outflows
    open_payables = get_open_transaction_balances(
        db, business_id, ("purchase", "expense"), as_of=ref_date
    )
    for item in open_payables:
        amt = item.balance_due
        if item.transaction_id in outflow_reductions_by_tx:
            pct = outflow_reductions_by_tx[item.transaction_id]
            amt = q4(amt * (Decimal("100") - pct) / Decimal("100"))
        if amt <= Decimal("0"):
            continue

        base_due = item.due_date if item.due_date is not None else day_1
        shifted_due = base_due + dt.timedelta(
            days=outflow_delays_by_tx.get(item.transaction_id, 0)
        )
        effective_due = day_1 if shifted_due <= ref_date else shifted_due

        if day_1 <= effective_due <= horizon_end_30:
            confirmed_out[effective_due] += amt
            label_prefix = "Overdue payable" if item.overdue else "Supplier payable"
            party_txt = item.party_name or "Supplier/Expense"
            outflow_causes.append(
                CashGapCauseOut(
                    kind="outflow",
                    label=f"{label_prefix}: {party_txt}",
                    amount=amt,
                    due_on=effective_due,
                    record_id=item.transaction_id,
                )
            )

    # 2. Derived open receivables -> expected inflows (overdue excluded unless overridden)
    open_receivables = get_open_transaction_balances(db, business_id, ("sale",), as_of=ref_date)
    for item in open_receivables:
        remaining = item.balance_due
        for mv in inflow_moves_by_tx.get(item.transaction_id, []):
            applied = min(remaining, q4(mv.amount))
            if applied > Decimal("0") and day_1 <= mv.new_date <= horizon_end_30:
                expected_in[mv.new_date] += applied
                remaining -= applied

        if remaining <= Decimal("0"):
            continue

        if item.due_date is not None and item.due_date > ref_date:
            if item.due_date <= horizon_end_30:
                expected_in[item.due_date] += remaining
        else:
            party_txt = item.party_name or "Customer"
            overdue_receivable_causes.append(
                CashGapCauseOut(
                    kind="overdue_receivable",
                    label=f"Overdue receivable: {party_txt}",
                    amount=q4(remaining),
                    due_on=item.due_date,
                    record_id=item.transaction_id,
                )
            )

    # 3. Active manual scheduled_events (ignore completed or cancelled)
    manual_events = (
        db.query(ScheduledEvent)
        .filter(
            ScheduledEvent.business_id == business_id,
            ScheduledEvent.status == "active",
            ScheduledEvent.expected_on <= horizon_end_30,
        )
        .all()
    )
    for ev in manual_events:
        effective_date = day_1 if ev.expected_on <= ref_date else ev.expected_on
        amt = q4(Decimal(ev.amount))
        if amt <= Decimal("0"):
            continue
        if ev.direction == "inflow":
            if ev.certainty == "confirmed":
                confirmed_in[effective_date] += amt
            else:
                expected_in[effective_date] += amt
        else:
            if ev.certainty == "confirmed":
                confirmed_out[effective_date] += amt
            else:
                expected_out[effective_date] += amt
            outflow_causes.append(
                CashGapCauseOut(
                    kind="outflow",
                    label=f"Scheduled outflow: {ev.label}",
                    amount=amt,
                    due_on=effective_date,
                    record_id=ev.id,
                )
            )

    # 4. Scenario extra outflows (e.g., planned_purchase)
    for extra in extra_outflows:
        effective_date = day_1 if extra.on <= ref_date else extra.on
        amt = q4(extra.amount)
        if day_1 <= effective_date <= horizon_end_30 and amt > Decimal("0"):
            confirmed_out[effective_date] += amt
            outflow_causes.append(
                CashGapCauseOut(
                    kind="outflow",
                    label=extra.label,
                    amount=amt,
                    due_on=effective_date,
                    record_id=None,
                )
            )

    # Simulate all 30 days once, then slice for requested horizon (7, 14, or 30).
    all_days: list[ForecastDayOut] = []
    running_cash = starting_cash
    for offset in range(1, MAX_HORIZON_DAYS + 1):
        day = ref_date + dt.timedelta(days=offset)
        opening = q4(running_cash)
        c_in = q4(confirmed_in[day])
        e_in = q4(expected_in[day])
        c_out = q4(confirmed_out[day])
        e_out = q4(expected_out[day])

        closing = q4(opening + c_in + e_in + est_inflow - c_out - e_out - est_outflow)
        all_days.append(
            ForecastDayOut(
                date=day,
                opening_cash=opening,
                confirmed_inflows=c_in,
                expected_inflows=e_in,
                estimated_inflows=est_inflow,
                confirmed_outflows=c_out,
                expected_outflows=e_out,
                estimated_outflows=est_outflow,
                closing_cash=closing,
                below_reserve=closing < min_reserve,
            )
        )
        running_cash = closing

    sliced_days = all_days[:days]

    # Earliest date wins on ties because we iterate chronologically with strict `<`.
    lowest_day = sliced_days[0]
    gap_start_date: dt.date | None = None
    for d in sliced_days:
        if gap_start_date is None and d.below_reserve:
            gap_start_date = d.date
        if d.closing_cash < lowest_day.closing_cash:
            lowest_day = d

    lowest_cash = lowest_day.closing_cash
    gap_vs_reserve = q4(max(ZERO, min_reserve - lowest_cash))
    gap_vs_zero = q4(max(ZERO, -lowest_cash))

    cutoff = lowest_day.date if gap_vs_reserve > ZERO else sliced_days[-1].date
    relevant_outflows = sorted(
        [c for c in outflow_causes if c.due_on is not None and c.due_on <= cutoff],
        key=lambda c: c.amount,
        reverse=True,
    )
    relevant_overdue = sorted(
        overdue_receivable_causes,
        key=lambda c: c.amount,
        reverse=True,
    )
    causes = (relevant_outflows + relevant_overdue)[:5]

    return ForecastResponse(
        currency=business.currency,
        as_of=ref_date,
        horizon_days=days,
        limited_data=bool(coverage["limited_data"]),
        history_days=int(coverage["history_days"]),
        min_cash_reserve=min_reserve,
        lowest_cash_amount=lowest_cash,
        lowest_cash_date=lowest_day.date,
        estimated_cash_gap_vs_reserve=gap_vs_reserve,
        estimated_cash_gap_vs_zero=gap_vs_zero,
        gap_start_date=gap_start_date,
        unlockable_slow_stock_value=inventory.slow_stock_value_flagged,
        assumptions_note=(
            "Conservative baseline: overdue payables land on day 1, overdue customer "
            "receivables are excluded until collected, and daily estimates reflect "
            "same-day cash activity only."
        ),
        causes=causes,
        daily=sliced_days,
    )
