from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

MONEY = Numeric(19, 4)
JSON_VARIANT = JSON().with_variant(JSONB, "postgresql")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    business: Mapped[Business | None] = relationship(
        back_populates="owner", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )


class Business(Base):
    __tablename__ = "businesses"
    __table_args__ = (
        CheckConstraint("min_cash_reserve >= 0", name="ck_businesses_min_cash_reserve_nonneg"),
        CheckConstraint(
            "slow_stock_days_threshold >= 1", name="ck_businesses_slow_stock_threshold_pos"
        ),
        CheckConstraint(
            "vertical IN ('grocery', 'service', 'other')", name="ck_businesses_vertical"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    vertical: Mapped[str] = mapped_column(String(32), nullable=False, default="grocery")
    currency: Mapped[str] = mapped_column(String(12), nullable=False, default="USD")
    min_cash_reserve: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.0000")
    )
    slow_stock_days_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    owner: Mapped[User] = relationship(back_populates="business")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("business_id", "sku", name="uq_products_business_sku"),
        CheckConstraint("kind IN ('goods', 'service')", name="ck_products_kind"),
        CheckConstraint("reorder_level >= 0", name="ck_products_reorder_level_nonneg"),
        CheckConstraint("sale_price >= 0", name="ck_products_sale_price_nonneg"),
        CheckConstraint("avg_cost >= 0", name="ck_products_avg_cost_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="goods")
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="pcs")
    track_inventory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reorder_level: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.0000")
    )
    sale_price: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.0000")
    )
    avg_cost: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.0000")
    )
    expiry_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_business_date", "business_id", "date"),
        Index(
            "uq_transactions_business_idempotency",
            "business_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        CheckConstraint(
            "type IN ('sale', 'purchase', 'expense', 'sale_return', 'purchase_return')",
            name="ck_transactions_type",
        ),
        CheckConstraint("status IN ('posted', 'void')", name="ck_transactions_status"),
        CheckConstraint("total >= 0", name="ck_transactions_total_nonneg"),
        CheckConstraint("discount >= 0", name="ck_transactions_discount_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    original_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    discount: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.0000")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="posted")
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    items: Mapped[list[TransactionItem]] = relationship(
        cascade="all, delete-orphan", order_by="TransactionItem.id"
    )


class TransactionItem(Base):
    __tablename__ = "transaction_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_transaction_items_qty_pos"),
        CheckConstraint("unit_price >= 0", name="ck_transaction_items_unit_price_nonneg"),
        CheckConstraint(
            "unit_cost_snapshot >= 0", name="ck_transaction_items_unit_cost_nonneg"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    unit_cost_snapshot: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.0000")
    )


class CashMovement(Base):
    __tablename__ = "cash_movements"
    __table_args__ = (
        Index("ix_cash_movements_business_date", "business_id", "date"),
        Index(
            "uq_cash_movements_business_idempotency",
            "business_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        CheckConstraint(
            "kind IN ('opening', 'payment', 'refund', 'manual')",
            name="ck_cash_movements_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    signed_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="payment")
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        Index("ix_inventory_movements_business_product", "business_id", "product_id"),
        Index("ix_inventory_movements_business_date", "business_id", "date"),
        CheckConstraint("unit_cost >= 0", name="ck_inventory_movements_unit_cost_nonneg"),
        CheckConstraint(
            "type IN ('opening', 'purchase', 'sale', 'return', 'adjust')",
            name="ck_inventory_movements_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    qty_delta: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.0000")
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ScheduledEvent(Base):
    __tablename__ = "scheduled_events"
    __table_args__ = (
        Index("ix_scheduled_events_business_expected_on", "business_id", "expected_on"),
        CheckConstraint("amount >= 0", name="ck_scheduled_events_amount_nonneg"),
        CheckConstraint(
            "direction IN ('inflow', 'outflow')", name="ck_scheduled_events_direction"
        ),
        CheckConstraint(
            "certainty IN ('confirmed', 'expected')", name="ck_scheduled_events_certainty"
        ),
        CheckConstraint(
            "status IN ('active', 'completed', 'cancelled')",
            name="ck_scheduled_events_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    expected_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    certainty: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdvisorLog(Base):
    __tablename__ = "advisor_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    tools_called: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_VARIANT, nullable=False, default=list
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
