"""Read-only, tenant-scoped, Pydantic-validated tools for the AI Advisor."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.schemas import ScenarioRequest
from app.services import finance, forecast, readiness, scenario
from app.services.finance import ZERO, q4

MAX_PARTIES_RETURNED = 5
MAX_FORECAST_PREVIEW_DAYS = 7
MAX_NAME_LEN = 60


def _sanitize_label(raw: str | None, max_len: int = MAX_NAME_LEN) -> str:
    """Strip control characters/newlines and truncate untrusted names for LLM data safety."""
    if not raw:
        return ""
    cleaned = re.sub(r"[\r\n\t\x00-\x1f\x7f]+", " ", raw).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 3].rstrip() + "..."
    return cleaned


class EmptyToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ForecastCashInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: Literal[7, 14, 30] = 14


class ReadinessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: Literal[14, 30] = 14


class ProfitWindowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(default=30, ge=1, le=365)


class RunScenarioInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["collect_dues", "delay_payment", "reorder_less", "planned_purchase"]
    horizon_days: Literal[7, 14, 30] = 14
    collect_pct: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("100"))
    delay_days: int | None = Field(default=None, ge=1, le=60)
    transaction_id: uuid.UUID | None = None
    scheduled_event_id: uuid.UUID | None = None
    reorder_reduction_pct: Decimal | None = Field(
        default=None, ge=Decimal("0"), le=Decimal("100")
    )
    planned_purchase_amount: Decimal | None = Field(default=None, gt=Decimal("0"))
    planned_purchase_date: dt.date | None = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[Session, uuid.UUID, dt.date, BaseModel], dict[str, Any]]


def _handle_get_financial_snapshot(
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date,
    _args: BaseModel,
) -> dict[str, Any]:
    cash_pos = finance.get_cash_position(db, business_id, as_of=as_of)
    rec = finance.get_receivables(db, business_id, as_of=as_of)
    pay = finance.get_payables(db, business_id, as_of=as_of)
    inv = finance.get_inventory_insights(db, business_id, as_of=as_of)
    cov = finance.get_data_coverage(db, business_id, as_of=as_of)

    overdue_amt = Decimal(rec["overdue_amount"])  # type: ignore[arg-type]
    trapped_capital = q4(overdue_amt + inv.slow_stock_value_flagged)

    top_overdue = [
        {
            "customer_id": str(p["party_id"]) if p["party_id"] else None,
            "name": _sanitize_label(str(p["party_name"])),
            "overdue_amount": str(p["overdue_amount"]),
            "balance_due": str(p["balance_due"]),
            "earliest_due_date": p["earliest_due_date"].isoformat()
            if p["earliest_due_date"]
            else None,
        }
        for p in rec["parties"]  # type: ignore[index]
        if Decimal(p["overdue_amount"]) > ZERO
    ][:MAX_PARTIES_RETURNED]

    top_payables = [
        {
            "supplier_id": str(p["party_id"]) if p["party_id"] else None,
            "name": _sanitize_label(str(p["party_name"])),
            "balance_due": str(p["balance_due"]),
            "overdue_amount": str(p["overdue_amount"]),
            "earliest_due_date": p["earliest_due_date"].isoformat()
            if p["earliest_due_date"]
            else None,
        }
        for p in pay["parties"]  # type: ignore[index]
    ][:MAX_PARTIES_RETURNED]

    slow_items = sorted(
        [item for item in inv.items if item.slow_stock],
        key=lambda i: i.stock_value,
        reverse=True,
    )[:MAX_PARTIES_RETURNED]

    record_ids = [
        item["customer_id"]
        for item in top_overdue
        if item["customer_id"] is not None
    ] + [
        item["supplier_id"]
        for item in top_payables
        if item["supplier_id"] is not None
    ] + [str(item.product_id) for item in slow_items]

    return {
        "currency": str(cash_pos["currency"]),
        "as_of": as_of.isoformat(),
        "cash_on_hand": str(cash_pos["cash_on_hand"]),
        "min_cash_reserve": str(cash_pos["min_cash_reserve"]),
        "customers_owe": str(rec["total"]),
        "overdue_receivables": str(overdue_amt),
        "we_owe_suppliers": str(pay["total"]),
        "overdue_payables": str(pay["overdue_amount"]),
        "total_stock_value": str(inv.total_stock_value),
        "slow_stock_value_flagged": str(inv.slow_stock_value_flagged),
        "trapped_internal_capital": str(trapped_capital),
        "top_overdue_customers": top_overdue,
        "top_payables": top_payables,
        "top_slow_stock": [
            {
                "product_id": str(item.product_id),
                "name": _sanitize_label(item.name),
                "sku": _sanitize_label(item.sku, 32),
                "stock_value": str(item.stock_value),
                "days_of_stock": str(item.days_of_stock) if item.days_of_stock else None,
            }
            for item in slow_items
        ],
        "data_coverage": {
            "history_days": cov["history_days"],
            "limited_data": cov["limited_data"],
            "opening_cash_set": cov["opening_cash_set"],
            "incomplete_data": cov["incomplete_data"],
        },
        "record_ids": record_ids,
    }


def _handle_forecast_cash(
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date,
    args: BaseModel,
) -> dict[str, Any]:
    parsed = ForecastCashInput.model_validate(args)
    fc = forecast.build_forecast(db, business_id, days=parsed.days, as_of=as_of)
    rec = finance.get_receivables(db, business_id, as_of=as_of)
    trapped = q4(Decimal(rec["overdue_amount"]) + fc.unlockable_slow_stock_value)  # type: ignore[arg-type]
    gap_vs_trapped = q4(trapped - fc.estimated_cash_gap_vs_reserve)

    # Compact preview: first 5-7 days only (never dump all 30 daily rows into context)
    preview_days = fc.daily[:MAX_FORECAST_PREVIEW_DAYS]
    record_ids = [str(c.record_id) for c in fc.causes if c.record_id is not None]

    return {
        "currency": fc.currency,
        "as_of": fc.as_of.isoformat(),
        "horizon_days": fc.horizon_days,
        "limited_data": fc.limited_data,
        "history_days": fc.history_days,
        "min_cash_reserve": str(fc.min_cash_reserve),
        "lowest_cash_amount": str(fc.lowest_cash_amount),
        "lowest_cash_date": fc.lowest_cash_date.isoformat(),
        "estimated_cash_gap_vs_reserve": str(fc.estimated_cash_gap_vs_reserve),
        "estimated_cash_gap_vs_zero": str(fc.estimated_cash_gap_vs_zero),
        "gap_start_date": fc.gap_start_date.isoformat() if fc.gap_start_date else None,
        "unlockable_slow_stock_value": str(fc.unlockable_slow_stock_value),
        "trapped_internal_capital": str(trapped),
        "gap_vs_trapped_capital": str(gap_vs_trapped),
        "assumptions_note": fc.assumptions_note,
        "causes": [
            {
                "kind": c.kind,
                "label": _sanitize_label(c.label),
                "amount": str(c.amount),
                "due_on": c.due_on.isoformat() if c.due_on else None,
                "record_id": str(c.record_id) if c.record_id else None,
            }
            for c in fc.causes[:MAX_PARTIES_RETURNED]
        ],
        "next_days": [
            {
                "date": d.date.isoformat(),
                "closing_cash": str(d.closing_cash),
                "confirmed_outflows": str(d.confirmed_outflows),
                "expected_inflows": str(d.expected_inflows),
                "below_reserve": d.below_reserve,
            }
            for d in preview_days
        ],
        "record_ids": record_ids,
    }


def _handle_get_financial_readiness(
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date,
    args: BaseModel,
) -> dict[str, Any]:
    parsed = ReadinessInput.model_validate(args)
    cash_pos = finance.get_cash_position(db, business_id, as_of=as_of)
    rec = finance.get_receivables(db, business_id, as_of=as_of)
    inv = finance.get_inventory_insights(db, business_id, as_of=as_of)
    cov = finance.get_data_coverage(db, business_id, as_of=as_of)
    fc = forecast.build_forecast(db, business_id, days=parsed.days, as_of=as_of)
    prof = readiness.evaluate_readiness(
        currency=str(cash_pos["currency"]),
        cash_position=cash_pos,
        receivables=rec,
        inventory=inv,
        coverage=cov,
        forecast=fc,
    )
    return {
        "currency": prof.currency,
        "overall_status": prof.overall_status,
        "disclaimer": prof.disclaimer,
        "dimensions": [
            {
                "key": dim.key,
                "label": dim.label,
                "status": dim.status,
                "summary": dim.summary,
                "evidence": dim.evidence,
                "improvement_action": dim.improvement_action,
            }
            for dim in prof.dimensions
        ],
        "record_ids": [],
    }


def _handle_get_profit_summary(
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date,
    args: BaseModel,
) -> dict[str, Any]:
    parsed = ProfitWindowInput.model_validate(args)
    prof = finance.get_profitability(db, business_id, days=parsed.days, as_of=as_of)
    return {
        "currency": prof.currency,
        "as_of": prof.as_of.isoformat(),
        "period_days": prof.period_days,
        "gross_sales": str(prof.gross_sales),
        "discounts": str(prof.discounts),
        "returns": str(prof.returns),
        "net_sales": str(prof.net_sales),
        "cogs": str(prof.cogs),
        "gross_profit": str(prof.gross_profit),
        "gross_margin_pct": str(prof.gross_margin_pct),
        "expenses": str(prof.expenses),
        "net_operating_profit": str(prof.net_operating_profit),
        "record_ids": [],
    }


def _handle_get_product_margin(
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date,
    args: BaseModel,
) -> dict[str, Any]:
    parsed = ProfitWindowInput.model_validate(args)
    prof = finance.get_profitability(db, business_id, days=parsed.days, as_of=as_of)
    sorted_by_margin = sorted(prof.products, key=lambda p: p.gross_margin_pct, reverse=True)
    top = sorted_by_margin[:MAX_PARTIES_RETURNED]
    return {
        "currency": prof.currency,
        "as_of": prof.as_of.isoformat(),
        "period_days": prof.period_days,
        "products": [
            {
                "product_id": str(p.product_id),
                "name": _sanitize_label(p.name),
                "sku": _sanitize_label(p.sku, 32),
                "qty_sold": str(p.qty_sold),
                "net_sales": str(p.net_sales),
                "cogs": str(p.cogs),
                "gross_profit": str(p.gross_profit),
                "gross_margin_pct": str(p.gross_margin_pct),
            }
            for p in top
        ],
        "record_ids": [str(p.product_id) for p in top],
    }


def _handle_run_scenario(
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date,
    args: BaseModel,
) -> dict[str, Any]:
    parsed = RunScenarioInput.model_validate(args)
    req = ScenarioRequest(
        type=parsed.type,
        horizon_days=parsed.horizon_days,
        collect_pct=parsed.collect_pct,
        delay_days=parsed.delay_days,
        transaction_id=parsed.transaction_id,
        scheduled_event_id=parsed.scheduled_event_id,
        reorder_reduction_pct=parsed.reorder_reduction_pct,
        planned_purchase_amount=parsed.planned_purchase_amount,
        planned_purchase_date=parsed.planned_purchase_date,
    )
    res = scenario.run_scenario(db, business_id, req, as_of=as_of)
    return {
        "currency": res.currency,
        "scenario_type": res.scenario_type,
        "horizon_days": res.baseline.horizon_days,
        "baseline_lowest_cash": str(res.baseline.lowest_cash_amount),
        "baseline_lowest_date": res.baseline.lowest_cash_date.isoformat(),
        "baseline_gap_vs_reserve": str(res.baseline.estimated_cash_gap_vs_reserve),
        "simulated_lowest_cash": str(res.simulated.lowest_cash_amount),
        "simulated_lowest_date": res.simulated.lowest_cash_date.isoformat(),
        "simulated_gap_vs_reserve": str(res.simulated.estimated_cash_gap_vs_reserve),
        "projected_cash_improvement": str(res.impact.projected_cash_improvement),
        "gap_reduction_vs_reserve": str(res.impact.gap_reduction_vs_reserve),
        "reserve_breach_days_avoided": res.impact.reserve_breach_days_avoided,
        "trapped_internal_capital": str(res.impact.trapped_internal_capital),
        "affordable_above_reserve": res.impact.affordable_above_reserve,
        "record_ids": [
            str(c.record_id)
            for c in res.simulated.causes[:MAX_PARTIES_RETURNED]
            if c.record_id is not None
        ],
    }


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "get_financial_snapshot": ToolDefinition(
        name="get_financial_snapshot",
        description=(
            "Get cash on hand, safety reserve, receivables/payables totals with top 5 parties, "
            "slow stock value flagged with top 5 items, trapped_internal_capital, and data coverage."
        ),
        input_model=EmptyToolInput,
        handler=_handle_get_financial_snapshot,
    ),
    "forecast_cash": ToolDefinition(
        name="forecast_cash",
        description=(
            "Project daily cash over 7, 14, or 30 days. Returns lowest cash balance & date, "
            "estimated cash gap vs reserve/zero, trapped_internal_capital, gap_vs_trapped_capital, "
            "top causes, and a 7-day preview."
        ),
        input_model=ForecastCashInput,
        handler=_handle_forecast_cash,
    ),
    "get_financial_readiness": ToolDefinition(
        name="get_financial_readiness",
        description=(
            "Get the transparent 4-dimension financial-readiness profile (green/amber/red) "
            "with evidence figures and improvement actions."
        ),
        input_model=ReadinessInput,
        handler=_handle_get_financial_readiness,
    ),
    "get_profit_summary": ToolDefinition(
        name="get_profit_summary",
        description="Get net sales, COGS, gross profit, gross margin %, expenses, and operating profit.",
        input_model=ProfitWindowInput,
        handler=_handle_get_profit_summary,
    ),
    "get_product_margin": ToolDefinition(
        name="get_product_margin",
        description="Get top products by gross profit and margin % over the selected period.",
        input_model=ProfitWindowInput,
        handler=_handle_get_product_margin,
    ),
    "run_scenario": ToolDefinition(
        name="run_scenario",
        description=(
            "Simulate collect_dues, delay_payment, reorder_less, or planned_purchase affordability "
            "against baseline without modifying records."
        ),
        input_model=RunScenarioInput,
        handler=_handle_run_scenario,
    ),
}


def execute_tool(
    name: str,
    raw_args: dict[str, Any],
    db: Session,
    business_id: uuid.UUID,
    as_of: dt.date,
) -> dict[str, Any]:
    """Validate tool parameters and execute read-only; returns error dict as data on failure."""
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        return {"error": f"Unknown tool '{name}'", "record_ids": []}

    cleaned_args = dict(raw_args or {})
    if "business_id" in cleaned_args or "user_id" in cleaned_args or "as_of" in cleaned_args:
        return {
            "error": "Tenant/date parameters are server-controlled and cannot be supplied",
            "record_ids": [],
        }

    try:
        validated = tool.input_model.model_validate(cleaned_args)
        return tool.handler(db, business_id, as_of, validated)
    except ValidationError as exc:
        return {"error": f"Invalid tool parameters: {exc.errors()[0]['msg']}", "record_ids": []}
    except HTTPException as exc:
        return {"error": str(exc.detail), "record_ids": []}
    except Exception as exc:
        return {"error": f"Tool execution error: {exc}", "record_ids": []}
