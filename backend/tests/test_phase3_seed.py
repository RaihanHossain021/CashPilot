import datetime as dt
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CashMovement, InventoryMovement, Product, Transaction
from app.seed import GROCERY_DEMO_EMAIL, GROCERY_DEMO_PASSWORD, seed_grocery_demo

FIXED_TODAY = dt.date(2026, 11, 28)


def test_seed_grocery_demo_exact_numbers_and_idempotency(
    client: TestClient, db_session: Session
) -> None:
    first = client.post(f"/api/v1/dev/seed?today={FIXED_TODAY.isoformat()}")
    assert first.status_code == 200
    second = client.post(f"/api/v1/dev/seed?today={FIXED_TODAY.isoformat()}")
    assert second.status_code == 200

    biz_id = uuid.UUID(second.json()["business_id"])

    # Demo user can log in and inspect transactions through the API.
    login = client.post(
        "/api/v1/auth/login",
        json={"email": GROCERY_DEMO_EMAIL, "password": GROCERY_DEMO_PASSWORD},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Cash on hand = 51,000 + 5,000 + (14 * 6,000) - 45,000 - 15,000 - 10,000 = 70,000.0000
    cash_on_hand = db_session.query(func.sum(CashMovement.signed_amount)).filter(
        CashMovement.business_id == biz_id
    ).scalar()
    assert cash_on_hand == Decimal("70000.0000")

    # Last 14 days operating cash inflows = 84,000 (6,000/day), outflows = 70,000 (5,000/day)
    window_start = FIXED_TODAY - dt.timedelta(days=13)
    recent_inflows = db_session.query(func.sum(CashMovement.signed_amount)).filter(
        CashMovement.business_id == biz_id,
        CashMovement.date >= window_start,
        CashMovement.date <= FIXED_TODAY,
        CashMovement.signed_amount > 0,
    ).scalar()
    recent_outflows = db_session.query(func.sum(CashMovement.signed_amount)).filter(
        CashMovement.business_id == biz_id,
        CashMovement.date >= window_start,
        CashMovement.date <= FIXED_TODAY,
        CashMovement.signed_amount < 0,
    ).scalar()
    assert recent_inflows == Decimal("84000.0000")
    assert recent_outflows == Decimal("-70000.0000")

    # Overdue customer receivables = 20,000 + 20,000 = 40,000.0000
    unpaid_sales = client.get("/api/v1/transactions?type=sale&unpaid_only=true", headers=headers).json()
    assert len(unpaid_sales) == 2
    assert sum(Decimal(tx["balance_due"]) for tx in unpaid_sales) == Decimal("40000.0000")
    assert all(dt.date.fromisoformat(tx["due_date"]) < FIXED_TODAY for tx in unpaid_sales)

    # Supplier payable due in 9 days = 90,000.0000
    unpaid_purchases = client.get(
        "/api/v1/transactions?type=purchase&unpaid_only=true", headers=headers
    ).json()
    assert len(unpaid_purchases) == 1
    assert Decimal(unpaid_purchases[0]["balance_due"]) == Decimal("90000.0000")
    assert unpaid_purchases[0]["due_date"] == (FIXED_TODAY + dt.timedelta(days=9)).isoformat()

    # Stock invariants: no negative stock, slow stock (0 sold) = 20,000 + 15,000 = 35,000.0000
    products = db_session.query(Product).filter(Product.business_id == biz_id).all()
    stock_by_sku: dict[str, Decimal] = {}
    value_by_sku: dict[str, Decimal] = {}
    for prod in products:
        qty = db_session.query(func.coalesce(func.sum(InventoryMovement.qty_delta), 0)).filter(
            InventoryMovement.business_id == biz_id,
            InventoryMovement.product_id == prod.id,
        ).scalar()
        qty_dec = Decimal(qty)
        assert qty_dec > Decimal("0")
        stock_by_sku[prod.sku] = qty_dec
        value_by_sku[prod.sku] = qty_dec * Decimal(prod.avg_cost)

    assert stock_by_sku == {
        "RICE-5KG": Decimal("125.0000"),
        "OIL-2L": Decimal("181.0000"),
        "SUGAR-1KG": Decimal("94.0000"),
        "OLIVE-TIN": Decimal("10.0000"),
        "SAFFRON-BOX": Decimal("10.0000"),
    }
    assert value_by_sku["OLIVE-TIN"] + value_by_sku["SAFFRON-BOX"] == Decimal("35000.0000")

    # Idempotency: only 19 transactions exist after reseeding twice (2 credit + 14 cash sales + 1 cash purchase + 1 credit purchase + 2 expenses = 20? Let's count exact: 2+14+2+2 = 20)
    assert db_session.query(Transaction).filter(Transaction.business_id == biz_id).count() == 20


def test_seed_endpoint_blocked_outside_dev(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    res = client.post("/api/v1/dev/seed")
    assert res.status_code == 403


def test_seed_does_not_wipe_existing_merchant(client: TestClient, db_session: Session) -> None:
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "real.merchant@example.com", "password": "password1234", "name": "Real"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    biz = client.post(
        "/api/v1/business",
        headers=headers,
        json={"name": "Real Shop", "vertical": "grocery", "currency": "BDT"},
    ).json()

    seed_grocery_demo(db_session, today=FIXED_TODAY)
    db_session.commit()

    fetched = client.get("/api/v1/business", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == biz["id"]


@pytest.mark.skip(reason="Enable in Phase 5 once forecast.py is implemented")
def test_seeded_grocery_forecast_shows_cash_gap_in_7_to_14_days() -> None:
    """Contract test: seeded grocery business must project a cash gap on today + 9."""
    raise NotImplementedError
