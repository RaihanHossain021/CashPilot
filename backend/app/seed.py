"""Deterministic, date-relative demo data seeder (Phase 3)."""

from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

if __name__ == "__main__":
    BACKEND_DIR = Path(__file__).resolve().parents[1]
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

from app.auth import hash_password
from app.db import SessionLocal
from app.models import Business, Customer, Product, Supplier, User
from app.schemas import (
    OpeningCashCreate,
    OpeningStockCreate,
    TransactionCreate,
    TransactionItemCreate,
)
from app.services import ledger

GROCERY_DEMO_EMAIL = "grocery.demo@cashpilot.local"
GROCERY_DEMO_PASSWORD = "demo-password-123"


def seed_grocery_demo(db: Session, today: dt.date | None = None) -> dict[str, str]:
    """Wipe and deterministically reseed the FreshBasket Mart grocery demo business."""
    ref_today = today or dt.date.today()

    existing_user = db.query(User).filter(User.email == GROCERY_DEMO_EMAIL).first()
    if existing_user is not None:
        db.query(User).filter(User.id == existing_user.id).delete(synchronize_session=False)
        db.expire_all()
        db.flush()

    user = User(
        email=GROCERY_DEMO_EMAIL,
        password_hash=hash_password(GROCERY_DEMO_PASSWORD),
        name="Tariq Rahman",
    )
    db.add(user)
    db.flush()

    business = Business(
        owner_id=user.id,
        name="FreshBasket Mart",
        vertical="grocery",
        currency="BDT",
        min_cash_reserve=Decimal("15000.0000"),
        slow_stock_days_threshold=45,
    )
    db.add(business)
    db.flush()

    karim = Customer(business_id=business.id, name="Karim Traders", phone="01711-000101")
    nadia = Customer(business_id=business.id, name="Nadia Catering", phone="01711-000102")
    walkin = Customer(business_id=business.id, name="Walk-In Retail", phone=None)
    padma = Supplier(business_id=business.id, name="Padma Wholesale", phone="01811-000201")
    metro = Supplier(business_id=business.id, name="Metro Distribution", phone="01811-000202")
    db.add_all([karim, nadia, walkin, padma, metro])
    db.flush()

    rice = Product(
        business_id=business.id,
        name="Basmati Rice 5kg",
        sku="RICE-5KG",
        kind="goods",
        unit="bag",
        track_inventory=True,
        reorder_level=Decimal("20.0000"),
        sale_price=Decimal("600.0000"),
        avg_cost=Decimal("450.0000"),
    )
    oil = Product(
        business_id=business.id,
        name="Soybean Oil 2L",
        sku="OIL-2L",
        kind="goods",
        unit="bottle",
        track_inventory=True,
        reorder_level=Decimal("25.0000"),
        sale_price=Decimal("400.0000"),
        avg_cost=Decimal("300.0000"),
    )
    sugar = Product(
        business_id=business.id,
        name="Refined Sugar 1kg",
        sku="SUGAR-1KG",
        kind="goods",
        unit="pack",
        track_inventory=True,
        reorder_level=Decimal("40.0000"),
        sale_price=Decimal("150.0000"),
        avg_cost=Decimal("110.0000"),
    )
    olive_oil = Product(
        business_id=business.id,
        name="Imported Olive Oil Tin 2L",
        sku="OLIVE-TIN",
        kind="goods",
        unit="tin",
        track_inventory=True,
        reorder_level=Decimal("2.0000"),
        sale_price=Decimal("2500.0000"),
        avg_cost=Decimal("2000.0000"),
    )
    saffron = Product(
        business_id=business.id,
        name="Gourmet Saffron Gift Box",
        sku="SAFFRON-BOX",
        kind="goods",
        unit="box",
        track_inventory=True,
        reorder_level=Decimal("2.0000"),
        sale_price=Decimal("2000.0000"),
        avg_cost=Decimal("1500.0000"),
    )
    db.add_all([rice, oil, sugar, olive_oil, saffron])
    db.flush()

    # 1. Opening balances at today - 35 days
    opening_date = ref_today - dt.timedelta(days=35)
    ledger.set_opening_cash(
        db,
        business.id,
        OpeningCashCreate(amount=Decimal("51000.0000"), date=opening_date, note="Opening cash"),
    )
    for prod, qty, cost in [
        (rice, Decimal("80"), Decimal("450")),
        (oil, Decimal("100"), Decimal("300")),
        (sugar, Decimal("150"), Decimal("110")),
        (olive_oil, Decimal("10"), Decimal("2000")),
        (saffron, Decimal("10"), Decimal("1500")),
    ]:
        ledger.set_opening_stock(
            db,
            business.id,
            OpeningStockCreate(product_id=prod.id, qty=qty, unit_cost=cost),
        )

    # 2. Overdue credit sales before the 14-day window (total overdue = 40,000)
    ledger.create_transaction(
        db,
        business.id,
        TransactionCreate(
            type="sale",
            customer_id=karim.id,
            date=ref_today - dt.timedelta(days=25),
            due_date=ref_today - dt.timedelta(days=5),
            paid_amount=Decimal("5000.0000"),
            idempotency_key="seed-credit-karim",
            notes="Credit wholesale order - overdue",
            items=[
                TransactionItemCreate(product_id=rice.id, qty=Decimal("25")),
                TransactionItemCreate(product_id=oil.id, qty=Decimal("25")),
            ],
        ),
    )
    ledger.create_transaction(
        db,
        business.id,
        TransactionCreate(
            type="sale",
            customer_id=nadia.id,
            date=ref_today - dt.timedelta(days=22),
            due_date=ref_today - dt.timedelta(days=2),
            paid_amount=Decimal("0.0000"),
            idempotency_key="seed-credit-nadia",
            notes="Catering credit invoice - overdue",
            items=[
                TransactionItemCreate(product_id=rice.id, qty=Decimal("20")),
                TransactionItemCreate(product_id=oil.id, qty=Decimal("20")),
            ],
        ),
    )

    # 3. Chronological 14-day history (today - 13 through today):
    #    Cash sales: 6,000/day * 14 = 84,000
    #    Cash outflows: 45,000 purchase (today - 12) + 15,000 rent (today - 7) + 10,000 wages (today - 3) = 70,000
    #    Net operating cash: +14,000 over 14 days (+1,000/day) -> Cash now = 70,000
    for offset in range(13, -1, -1):
        day = ref_today - dt.timedelta(days=offset)

        if offset == 12:
            # Restock before that day's sales
            ledger.create_transaction(
                db,
                business.id,
                TransactionCreate(
                    type="purchase",
                    supplier_id=padma.id,
                    date=day,
                    paid_amount=Decimal("45000.0000"),
                    idempotency_key="seed-cash-restock-12",
                    notes="Regular staple restock",
                    items=[
                        TransactionItemCreate(
                            product_id=rice.id, qty=Decimal("60"), unit_price=Decimal("450")
                        ),
                        TransactionItemCreate(
                            product_id=oil.id, qty=Decimal("60"), unit_price=Decimal("300")
                        ),
                    ],
                ),
            )

        if offset == 7:
            ledger.create_transaction(
                db,
                business.id,
                TransactionCreate(
                    type="expense",
                    date=day,
                    expense_amount=Decimal("15000.0000"),
                    paid_amount=Decimal("15000.0000"),
                    idempotency_key="seed-rent-7",
                    notes="Shop rent and utilities",
                ),
            )

        if offset == 3:
            ledger.create_transaction(
                db,
                business.id,
                TransactionCreate(
                    type="expense",
                    date=day,
                    expense_amount=Decimal("10000.0000"),
                    paid_amount=Decimal("10000.0000"),
                    idempotency_key="seed-wages-3",
                    notes="Staff wages",
                ),
            )

        if offset == 2:
            # Large credit supplier obligation due in 9 days (today + 9)
            ledger.create_transaction(
                db,
                business.id,
                TransactionCreate(
                    type="purchase",
                    supplier_id=metro.id,
                    date=day,
                    due_date=ref_today + dt.timedelta(days=9),
                    paid_amount=Decimal("0.0000"),
                    idempotency_key="seed-metro-due-9",
                    notes="Major bulk supplier invoice due in 9 days",
                    items=[
                        TransactionItemCreate(
                            product_id=rice.id, qty=Decimal("100"), unit_price=Decimal("450")
                        ),
                        TransactionItemCreate(
                            product_id=oil.id, qty=Decimal("150"), unit_price=Decimal("300")
                        ),
                    ],
                ),
            )

        ledger.create_transaction(
            db,
            business.id,
            TransactionCreate(
                type="sale",
                customer_id=walkin.id,
                date=day,
                paid_amount=Decimal("6000.0000"),
                idempotency_key=f"seed-daily-sale-{offset}",
                notes="Daily retail counter sales",
                items=[
                    TransactionItemCreate(product_id=rice.id, qty=Decimal("5")),
                    TransactionItemCreate(product_id=oil.id, qty=Decimal("6")),
                    TransactionItemCreate(product_id=sugar.id, qty=Decimal("4")),
                ],
            ),
        )

    db.flush()
    return {
        "business_id": str(business.id),
        "business_name": business.name,
        "demo_email": GROCERY_DEMO_EMAIL,
        "demo_password": GROCERY_DEMO_PASSWORD,
        "reference_date": ref_today.isoformat(),
    }


def main() -> None:
    with SessionLocal() as db:
        info = seed_grocery_demo(db)
        db.commit()
    print(f"Seeded demo business: {info}")


if __name__ == "__main__":
    main()
