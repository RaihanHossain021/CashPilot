"""Internal-capital-first rule-based recommendations (Phase 6)."""

from __future__ import annotations

from decimal import Decimal

from app.schemas import ForecastResponse, InventoryResponse, RecommendationOut
from app.services.finance import ZERO, q4


def build_recommendations(
    currency: str,
    receivables: dict[str, object],
    inventory: InventoryResponse,
    forecast: ForecastResponse,
) -> list[RecommendationOut]:
    """Generate deterministic recommendations prioritizing internal capital before borrowing."""
    recommendations: list[RecommendationOut] = []

    overdue_amt = Decimal(receivables["overdue_amount"])  # type: ignore[arg-type]
    gap_vs_reserve = forecast.estimated_cash_gap_vs_reserve
    gap_vs_zero = forecast.estimated_cash_gap_vs_zero
    slow_value = inventory.slow_stock_value_flagged
    internal_capital = q4(overdue_amt + slow_value)

    # 1. Collect overdue customer dues first
    if overdue_amt > ZERO:
        overdue_parties = [
            f"{p['party_name']} ({p['overdue_amount']} {currency})"
            for p in receivables["parties"]  # type: ignore[index]
            if Decimal(p["overdue_amount"]) > ZERO
        ][:3]
        party_list = ", ".join(overdue_parties) if overdue_parties else "overdue customers"
        if gap_vs_reserve > ZERO:
            covered = overdue_amt >= gap_vs_reserve
            impact = (
                f"Collecting these dues ({overdue_amt} {currency}) exceeds your projected "
                f"reserve gap of {gap_vs_reserve} {currency}."
                if covered
                else f"Collecting up to {overdue_amt} {currency} directly narrows your "
                f"{gap_vs_reserve} {currency} projected gap before any borrowing."
            )
        else:
            impact = f"Unlocks up to {overdue_amt} {currency} in overdue cash."

        recommendations.append(
            RecommendationOut(
                code="COLLECT_OVERDUE_DUES",
                title="Collect overdue customer dues first",
                issue=f"{overdue_amt} {currency} is overdue from {receivables['overdue_count']} open invoices.",
                evidence=f"Overdue balances: {party_list}.",
                suggested_action="Follow up on overdue invoices or offer a small early-settlement discount.",
                estimated_impact=impact,
                limitations="Assumes customers settle balances within the forecast window.",
            )
        )

    # 2. Unlock trapped capital in slow-moving stock before assuming new borrowing
    if slow_value > ZERO:
        slow_items = [item for item in inventory.items if item.slow_stock]
        top_slow = ", ".join(
            f"{item.name} ({item.stock_value} {currency})"
            for item in sorted(slow_items, key=lambda i: i.stock_value, reverse=True)[:3]
        )
        gap_note = (
            f"Combined with overdue dues, unlockable internal capital ({internal_capital} {currency}) "
            f"{'exceeds' if internal_capital >= gap_vs_reserve else 'helps offset'} the "
            f"{gap_vs_reserve} {currency} reserve gap without taking a loan."
            if gap_vs_reserve > ZERO
            else f"Frees {slow_value} {currency} ({inventory.slow_stock_pct_of_inventory}% of inventory)."
        )
        recommendations.append(
            RecommendationOut(
                code="RELEASE_SLOW_STOCK",
                title="Pause reorders and clear slow-moving stock before borrowing",
                issue=(
                    f"{slow_value} {currency} ({inventory.slow_stock_pct_of_inventory}% of stock value) "
                    f"is tied up in slow-moving items."
                ),
                evidence=f"Slow items flagged: {top_slow}.",
                suggested_action="Pause new reorders on slow SKUs and run targeted bundles/discounts to convert stock to cash.",
                estimated_impact=gap_note,
                limitations="Liquidation speed and margin discount depend on customer demand.",
            )
        )

    # 3. Negotiate or delay large supplier payment inside shortage window
    outflow_causes = [c for c in forecast.causes if c.kind == "outflow"]
    if gap_vs_reserve > ZERO and outflow_causes:
        top_outflow = outflow_causes[0]
        recommendations.append(
            RecommendationOut(
                code="DELAY_LARGE_PAYABLE",
                title="Negotiate or stagger upcoming supplier payment",
                issue=(
                    f"{top_outflow.label} ({top_outflow.amount} {currency}) on {top_outflow.due_on} "
                    f"drives the projected cash gap ({gap_vs_zero} {currency} below zero, "
                    f"{gap_vs_reserve} {currency} below reserve)."
                ),
                evidence=f"Peak cash deficit occurs on {forecast.lowest_cash_date} at {forecast.lowest_cash_amount} {currency}.",
                suggested_action="Test shifting this payment by 7–14 days in Scenario Lab or splitting into partial installments.",
                estimated_impact=f"Avoids up to {gap_vs_reserve} {currency} reserve breach if deferred past collections.",
                limitations="Requires supplier agreement; delaying only shifts timing rather than reducing total liability.",
            )
        )

    return recommendations
