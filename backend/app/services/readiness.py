"""Pure, threshold-based transparent financial-readiness profile (Phase 6).

This module has no database access. Every dimension evaluates explicit numeric
thresholds against backend-computed metrics and returns transparent evidence
plus actionable improvements. Never produces a credit score or loan decision.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from app.schemas import (
    ForecastResponse,
    InventoryResponse,
    ReadinessDimensionOut,
    ReadinessResponse,
)
from app.services.finance import ZERO, q4

Status = Literal["green", "amber", "red"]

# Explicit threshold constants
HISTORY_DAYS_GREEN = 14
LIQUIDITY_GREEN_MULT = Decimal("1.5")
LIQUIDITY_AMBER_MULT = Decimal("1.0")
SLOW_STOCK_GREEN_MAX_PCT = Decimal("10")
SLOW_STOCK_AMBER_MAX_PCT = Decimal("25")
OVERDUE_GREEN_MAX_PCT = Decimal("20")
OVERDUE_AMBER_MAX_PCT = Decimal("50")


def _worst_status(statuses: list[Status]) -> Status:
    if "red" in statuses:
        return "red"
    if "amber" in statuses:
        return "amber"
    return "green"


def evaluate_readiness(
    currency: str,
    cash_position: dict[str, object],
    receivables: dict[str, object],
    inventory: InventoryResponse,
    coverage: dict[str, object],
    forecast: ForecastResponse,
) -> ReadinessResponse:
    """Evaluate 4 transparent financial-readiness dimensions from backend metrics."""
    cash_on_hand = Decimal(cash_position["cash_on_hand"])  # type: ignore[arg-type]
    min_reserve = Decimal(cash_position["min_cash_reserve"])  # type: ignore[arg-type]
    opening_cash_set = bool(coverage["opening_cash_set"])
    history_days = int(coverage["history_days"])  # type: ignore[arg-type]
    missing_due = int(coverage["tx_missing_due_date"])  # type: ignore[arg-type]

    customers_owe = Decimal(receivables["total"])  # type: ignore[arg-type]
    overdue_receivables = Decimal(receivables["overdue_amount"])  # type: ignore[arg-type]
    overdue_pct = (
        q4(overdue_receivables / customers_owe * Decimal("100"))
        if customers_owe > ZERO
        else ZERO
    )

    # 1. Record completeness
    if not opening_cash_set:
        rec_status: Status = "red"
        rec_summary = "Opening cash is not recorded, so cash balances are incomplete."
        rec_action = "Record your opening cash balance in the Ledger."
    elif history_days < HISTORY_DAYS_GREEN or missing_due > 0:
        rec_status = "amber"
        rec_summary = (
            f"{history_days} days of records available; {missing_due} credit "
            "transactions are missing due dates."
        )
        rec_action = (
            "Keep recording daily activity past 14 days and ensure credit entries have due dates."
        )
    else:
        rec_status = "green"
        rec_summary = f"{history_days} days of complete records with opening cash and due dates."
        rec_action = "Maintain daily ledger entry consistency."

    dim_records = ReadinessDimensionOut(
        key="record_completeness",
        label="Record completeness",
        status=rec_status,
        summary=rec_summary,
        evidence={
            "opening_cash_set": str(opening_cash_set).lower(),
            "history_days": str(history_days),
            "tx_missing_due_date": str(missing_due),
        },
        improvement_action=rec_action,
    )

    # 2. Liquidity buffer (cash now vs. reserve)
    if min_reserve == ZERO:
        liq_status: Status = "green" if cash_on_hand > ZERO else "red"
        liq_ratio = "n/a (reserve is 0)"
    else:
        ratio = q4(cash_on_hand / min_reserve)
        liq_ratio = f"{ratio}x"
        if cash_on_hand >= min_reserve * LIQUIDITY_GREEN_MULT:
            liq_status = "green"
        elif cash_on_hand >= min_reserve * LIQUIDITY_AMBER_MULT:
            liq_status = "amber"
        else:
            liq_status = "red"

    dim_liquidity = ReadinessDimensionOut(
        key="liquidity_buffer",
        label="Current liquidity buffer",
        status=liq_status,
        summary=f"Cash on hand is {cash_on_hand} {currency} vs. {min_reserve} {currency} reserve.",
        evidence={
            "cash_on_hand": str(cash_on_hand),
            "min_cash_reserve": str(min_reserve),
            "reserve_coverage_ratio": liq_ratio,
        },
        improvement_action=(
            "Maintain at least 1.5x your minimum cash reserve on hand."
            if liq_status != "green"
            else "Current cash buffer comfortably exceeds your reserve."
        ),
    )

    # 3. Projected resilience (lowest projected cash over forecast window)
    lowest_cash = forecast.lowest_cash_amount
    if lowest_cash < ZERO:
        proj_status: Status = "red"
        proj_summary = (
            f"Projected cash drops to {lowest_cash} {currency} on {forecast.lowest_cash_date} "
            f"(gap of {forecast.estimated_cash_gap_vs_zero} {currency} below zero)."
        )
        proj_action = (
            "Release trapped cash via overdue dues or slow stock, or defer upcoming payables "
            "before considering new borrowing."
        )
    elif lowest_cash < min_reserve:
        proj_status = "amber"
        proj_summary = (
            f"Cash stays positive ({lowest_cash} {currency}) but dips below your "
            f"{min_reserve} {currency} reserve on {forecast.lowest_cash_date}."
        )
        proj_action = "Pull forward customer collections or trim upcoming reorders to protect reserve."
    else:
        proj_status = "green"
        proj_summary = (
            f"Lowest projected balance ({lowest_cash} {currency}) stays above reserve "
            f"across the {forecast.horizon_days}-day window."
        )
        proj_action = "Projected cash stays above your safety reserve."

    dim_resilience = ReadinessDimensionOut(
        key="projected_resilience",
        label="Projected cash resilience",
        status=proj_status,
        summary=proj_summary,
        evidence={
            "horizon_days": str(forecast.horizon_days),
            "lowest_cash_amount": str(lowest_cash),
            "lowest_cash_date": forecast.lowest_cash_date.isoformat(),
            "estimated_cash_gap_vs_reserve": str(forecast.estimated_cash_gap_vs_reserve),
            "estimated_cash_gap_vs_zero": str(forecast.estimated_cash_gap_vs_zero),
        },
        improvement_action=proj_action,
    )

    # 4. Working-capital efficiency (slow stock & overdue receivables)
    slow_pct = inventory.slow_stock_pct_of_inventory
    if slow_pct > SLOW_STOCK_AMBER_MAX_PCT or overdue_pct > OVERDUE_AMBER_MAX_PCT:
        wc_status: Status = "red"
    elif slow_pct >= SLOW_STOCK_GREEN_MAX_PCT or overdue_pct >= OVERDUE_GREEN_MAX_PCT:
        wc_status = "amber"
    else:
        wc_status = "green"

    dim_wc = ReadinessDimensionOut(
        key="working_capital_efficiency",
        label="Working-capital efficiency",
        status=wc_status,
        summary=(
            f"{inventory.slow_stock_value_flagged} {currency} ({slow_pct}%) tied up in slow stock; "
            f"{overdue_receivables} {currency} ({overdue_pct}%) in overdue receivables."
        ),
        evidence={
            "slow_stock_value_flagged": str(inventory.slow_stock_value_flagged),
            "slow_stock_pct_of_inventory": str(slow_pct),
            "overdue_receivables": str(overdue_receivables),
            "overdue_receivables_pct": str(overdue_pct),
        },
        improvement_action=(
            "Follow up on overdue invoices and pause/discount slow-moving stock to free cash."
            if wc_status != "green"
            else "Stock velocity and receivables collection are healthy."
        ),
    )

    dimensions = [dim_records, dim_liquidity, dim_resilience, dim_wc]
    return ReadinessResponse(
        currency=currency,
        overall_status=_worst_status([d.status for d in dimensions]),
        dimensions=dimensions,
    )
