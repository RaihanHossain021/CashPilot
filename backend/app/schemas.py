"""Pydantic schemas for CashPilot.

Note for frontend consumers: Pydantic v2 serializes Python ``Decimal`` fields
as JSON strings (for example ``"15000.0000"``) to preserve financial precision.
"""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Phase 1: Auth, Business, and Master Data
# ---------------------------------------------------------------------------


class UserRegister(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError("Invalid email address")
        return cleaned

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Name cannot be blank")
        return cleaned


class UserLogin(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    created_at: dt.datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


class BusinessCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    vertical: Literal["grocery", "service", "other"] = "grocery"
    currency: str = Field(default="USD", min_length=1, max_length=12)
    min_cash_reserve: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0"))
    slow_stock_days_threshold: int = Field(default=45, ge=1, le=365)


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    vertical: str
    currency: str
    min_cash_reserve: Decimal
    slow_stock_days_threshold: int
    created_at: dt.datetime


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    phone: str | None


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    phone: str | None


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=64)
    kind: Literal["goods", "service"] = "goods"
    unit: str = Field(default="pcs", min_length=1, max_length=32)
    track_inventory: bool = True
    reorder_level: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0"))
    sale_price: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0"))
    avg_cost: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0"))
    expiry_date: dt.date | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    name: str
    sku: str
    kind: str
    unit: str
    track_inventory: bool
    reorder_level: Decimal
    sale_price: Decimal
    avg_cost: Decimal
    expiry_date: dt.date | None


# ---------------------------------------------------------------------------
# Frozen Response Contracts for Parallel Frontend / Later Phases
# (Decimal fields serialize as strings in JSON.)
# ---------------------------------------------------------------------------


class ForecastDayOut(BaseModel):
    date: dt.date
    opening_cash: Decimal
    confirmed_inflows: Decimal
    expected_inflows: Decimal
    estimated_inflows: Decimal
    confirmed_outflows: Decimal
    expected_outflows: Decimal
    closing_cash: Decimal
    below_reserve: bool


class CashGapCauseOut(BaseModel):
    kind: Literal["outflow", "overdue_receivable", "slow_stock"]
    label: str
    amount: Decimal
    due_on: dt.date | None = None
    record_id: uuid.UUID | None = None


class ForecastResponse(BaseModel):
    currency: str
    horizon_days: Literal[7, 14, 30]
    limited_data: bool
    history_days: int
    min_cash_reserve: Decimal
    lowest_cash_amount: Decimal
    lowest_cash_date: dt.date
    estimated_cash_gap_vs_reserve: Decimal
    estimated_cash_gap_vs_zero: Decimal
    gap_start_date: dt.date | None = None
    causes: list[CashGapCauseOut]
    daily: list[ForecastDayOut]


class ReadinessDimensionOut(BaseModel):
    key: str
    label: str
    status: Literal["green", "amber", "red"]
    summary: str
    evidence: dict[str, str]
    improvement_action: str


class ReadinessResponse(BaseModel):
    currency: str
    overall_status: Literal["green", "amber", "red"]
    disclaimer: str = (
        "Transparent financial-readiness profile for decision support only; "
        "not a credit score or lending decision."
    )
    dimensions: list[ReadinessDimensionOut]


class RecommendationOut(BaseModel):
    code: str
    title: str
    issue: str
    evidence: str
    suggested_action: str
    estimated_impact: str
    limitations: str


class DashboardResponse(BaseModel):
    currency: str
    period_days: int = 30
    cash_on_hand: Decimal
    min_cash_reserve: Decimal
    customers_owe: Decimal
    overdue_receivables: Decimal
    we_owe_suppliers: Decimal
    total_stock_value: Decimal
    slow_stock_value_flagged: Decimal
    slow_stock_pct_of_inventory: Decimal
    estimated_cash_gap_vs_reserve: Decimal
    estimated_cash_gap_vs_zero: Decimal
    gap_date: dt.date | None = None
    incomplete_data: bool
    readiness_summary: ReadinessResponse
    recommendations: list[RecommendationOut]


class ScenarioRequest(BaseModel):
    type: Literal["collect_dues", "delay_payment", "reorder_less", "planned_purchase"]
    horizon_days: Literal[7, 14, 30] = 14
    collect_pct: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("100"))
    delay_days: int | None = Field(default=None, ge=1, le=60)
    transaction_id: uuid.UUID | None = None
    reorder_reduction_pct: Decimal | None = Field(
        default=None, ge=Decimal("0"), le=Decimal("100")
    )
    planned_purchase_amount: Decimal | None = Field(default=None, gt=Decimal("0"))
    planned_purchase_date: dt.date | None = None


class ScenarioImpactOut(BaseModel):
    projected_cash_improvement: Decimal
    gap_reduction_vs_reserve: Decimal
    reserve_breach_days_avoided: int
    affordable_above_reserve: bool | None = None


class ScenarioResponse(BaseModel):
    currency: str
    scenario_type: str
    baseline: ForecastResponse
    simulated: ForecastResponse
    impact: ScenarioImpactOut
