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
# Phase 2: Ledger (Transactions, Payments, Returns, Opening Balances)
# ---------------------------------------------------------------------------


class TransactionItemCreate(BaseModel):
    product_id: uuid.UUID | None = None
    qty: Decimal = Field(gt=Decimal("0"))
    unit_price: Decimal | None = Field(default=None, ge=Decimal("0"))


class TransactionItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID | None
    qty: Decimal
    unit_price: Decimal
    unit_cost_snapshot: Decimal


class TransactionCreate(BaseModel):
    type: Literal["sale", "purchase", "expense", "sale_return", "purchase_return"]
    original_transaction_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    date: dt.date
    due_date: dt.date | None = None
    discount: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0"))
    paid_amount: Decimal = Field(default=Decimal("0.0000"), ge=Decimal("0"))
    expense_amount: Decimal | None = Field(default=None, ge=Decimal("0"))
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)
    items: list[TransactionItemCreate] = Field(default_factory=list)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    type: str
    original_transaction_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    supplier_id: uuid.UUID | None
    date: dt.date
    due_date: dt.date | None
    total: Decimal
    discount: Decimal
    status: str
    idempotency_key: str | None
    notes: str | None
    created_at: dt.datetime
    amount_paid: Decimal
    returns_total: Decimal
    balance_due: Decimal
    items: list[TransactionItemOut]


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=Decimal("0"))
    date: dt.date
    idempotency_key: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=500)


class CashMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    date: dt.date
    signed_amount: Decimal
    kind: str
    transaction_id: uuid.UUID | None
    idempotency_key: str | None
    note: str | None
    created_at: dt.datetime


class OpeningCashCreate(BaseModel):
    amount: Decimal = Field(ge=Decimal("0"))
    date: dt.date
    note: str | None = Field(default="Opening cash", max_length=500)


class OpeningStockCreate(BaseModel):
    product_id: uuid.UUID
    qty: Decimal = Field(gt=Decimal("0"))
    unit_cost: Decimal = Field(ge=Decimal("0"))
    date: dt.date | None = None
    note: str | None = Field(default="Opening stock", max_length=500)


class InventoryMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    product_id: uuid.UUID
    date: dt.date
    qty_delta: Decimal
    unit_cost: Decimal
    type: str
    transaction_id: uuid.UUID | None
    created_at: dt.datetime


# ---------------------------------------------------------------------------
# Phase 4: Finance Engine Reports (Inventory, Profitability, Coverage)
# ---------------------------------------------------------------------------


class InventoryItemOut(BaseModel):
    product_id: uuid.UUID
    name: str
    sku: str
    unit: str
    track_inventory: bool
    on_hand_qty: Decimal
    avg_cost: Decimal
    stock_value: Decimal
    sale_price: Decimal
    reorder_level: Decimal
    units_sold_window: Decimal
    daily_velocity: Decimal
    days_of_stock: Decimal | None
    slow_stock: bool
    low_stock: bool
    first_received_date: dt.date | None


class InventoryResponse(BaseModel):
    currency: str
    as_of: dt.date
    velocity_window_days: int
    slow_stock_days_threshold: int
    total_stock_value: Decimal
    slow_stock_value_flagged: Decimal
    slow_stock_pct_of_inventory: Decimal
    items: list[InventoryItemOut]


class ProductMarginOut(BaseModel):
    product_id: uuid.UUID
    name: str
    sku: str
    qty_sold: Decimal
    net_sales: Decimal
    cogs: Decimal
    gross_profit: Decimal
    gross_margin_pct: Decimal


class ProfitabilityResponse(BaseModel):
    currency: str
    as_of: dt.date
    period_days: int
    gross_sales: Decimal
    discounts: Decimal
    returns: Decimal
    net_sales: Decimal
    cogs: Decimal
    gross_profit: Decimal
    gross_margin_pct: Decimal
    expenses: Decimal
    net_operating_profit: Decimal
    products: list[ProductMarginOut]


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
    estimated_outflows: Decimal
    closing_cash: Decimal
    below_reserve: bool


class CashGapCauseOut(BaseModel):
    kind: Literal["outflow", "overdue_receivable"]
    label: str
    amount: Decimal
    due_on: dt.date | None = None
    record_id: uuid.UUID | None = None


class ForecastResponse(BaseModel):
    currency: str
    as_of: dt.date
    horizon_days: Literal[7, 14, 30]
    limited_data: bool
    history_days: int
    min_cash_reserve: Decimal
    lowest_cash_amount: Decimal
    lowest_cash_date: dt.date
    estimated_cash_gap_vs_reserve: Decimal
    estimated_cash_gap_vs_zero: Decimal
    gap_start_date: dt.date | None = None
    unlockable_slow_stock_value: Decimal
    assumptions_note: str
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
    scheduled_event_id: uuid.UUID | None = None
    reorder_reduction_pct: Decimal | None = Field(
        default=None, ge=Decimal("0"), le=Decimal("100")
    )
    planned_purchase_amount: Decimal | None = Field(default=None, gt=Decimal("0"))
    planned_purchase_date: dt.date | None = None


class ScenarioImpactOut(BaseModel):
    projected_cash_improvement: Decimal
    gap_reduction_vs_reserve: Decimal
    reserve_breach_days_avoided: int
    trapped_internal_capital: Decimal
    affordable_above_reserve: bool | None = None


class ScenarioResponse(BaseModel):
    currency: str
    scenario_type: str
    baseline: ForecastResponse
    simulated: ForecastResponse
    impact: ScenarioImpactOut


# ---------------------------------------------------------------------------
# Phase 7: AI Advisor
# ---------------------------------------------------------------------------


class AdvisorAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question cannot be blank")
        return cleaned


class AdvisorFigureOut(BaseModel):
    label: str
    value: Decimal
    unit: str
    tool: str
    field: str


class AdvisorToolCallOut(BaseModel):
    tool: str
    args: dict[str, object]
    summary: str


class AdvisorAskResponse(BaseModel):
    summary: str
    figures: list[AdvisorFigureOut]
    evidence: list[str]
    assumptions: list[str]
    limitations: list[str]
    tools_called: list[AdvisorToolCallOut]
    number_check_passed: bool
    fallback_used: bool
    log_id: uuid.UUID


class AdvisorLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    answer: str
    tools_called: list[dict[str, object]]
    created_at: dt.datetime


class BusinessUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    vertical: Literal["grocery", "service", "other"] | None = None
    currency: str | None = Field(default=None, min_length=1, max_length=12)
    min_cash_reserve: Decimal | None = Field(default=None, ge=Decimal("0"))
    slow_stock_days_threshold: int | None = Field(default=None, ge=1, le=365)


class PartyBalanceOut(BaseModel):
    id: uuid.UUID
    kind: Literal["customer", "supplier"]
    name: str
    phone: str | None
    balance_due: Decimal
    overdue_amount: Decimal
    earliest_due_date: dt.date | None


class PartiesBalanceResponse(BaseModel):
    currency: str
    as_of: dt.date
    customers: list[PartyBalanceOut]
    suppliers: list[PartyBalanceOut]
