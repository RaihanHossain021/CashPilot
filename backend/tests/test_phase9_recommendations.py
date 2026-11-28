import datetime as dt
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.seed import GROCERY_DEMO_EMAIL, GROCERY_DEMO_PASSWORD, seed_grocery_demo

AS_OF = dt.date(2026, 11, 28)


def _setup_merchant(client: TestClient, email: str, reserve: str) -> dict[str, str]:
    token = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password1234", "name": "Owner"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post(
        "/api/v1/business",
        headers=headers,
        json={
            "name": f"Shop {email}",
            "vertical": "grocery",
            "currency": "BDT",
            "min_cash_reserve": reserve,
            "slow_stock_days_threshold": 30,
        },
    )
    return headers


def test_recommendations_shared_with_dashboard_and_contract_valid(
    client: TestClient, db_session: Session
) -> None:
    today = dt.date.today()
    seed_grocery_demo(db_session, today=today)
    db_session.commit()
    token = client.post(
        "/api/v1/auth/login",
        json={"email": GROCERY_DEMO_EMAIL, "password": GROCERY_DEMO_PASSWORD},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    dash = client.get("/api/v1/dashboard?days=14", headers=headers).json()
    rec_bundle = client.get("/api/v1/recommendations?days=14", headers=headers).json()

    assert rec_bundle["recommendations"] == dash["recommendations"]
    recs = rec_bundle["recommendations"]
    assert [r["code"] for r in recs] == [
        "COLLECT_OVERDUE_DUES",
        "RELEASE_SLOW_STOCK",
        "DELAY_LARGE_PAYABLE",
    ]
    # Ranked strictly by priority ascending
    assert [r["priority"] for r in recs] == sorted(r["priority"] for r in recs)

    # Contract test: every suggested_scenario executes cleanly against POST /api/v1/scenarios
    for rec in recs:
        if rec["suggested_scenario"] is not None:
            sc_res = client.post(
                "/api/v1/scenarios",
                headers=headers,
                json=rec["suggested_scenario"],
            )
            assert sc_res.status_code == 200


def test_recommendations_edge_cases_incomplete_healthy_and_no_scheduled_reorder(
    client: TestClient,
) -> None:
    today = dt.date.today()

    # 1. Missing opening cash -> ONLY SET_OPENING_CASH recommendation
    h_inc = _setup_merchant(client, "inc@example.com", "5000")
    sup = client.post("/api/v1/suppliers", headers=h_inc, json={"name": "Sup"}).json()
    prod = client.post(
        "/api/v1/products",
        headers=h_inc,
        json={"name": "Oil", "sku": "O-1", "sale_price": "100"},
    ).json()
    client.post(
        "/api/v1/transactions",
        headers=h_inc,
        json={
            "type": "purchase",
            "supplier_id": sup["id"],
            "date": today.isoformat(),
            "due_date": (today + dt.timedelta(days=5)).isoformat(),
            "paid_amount": "0",
            "items": [{"product_id": prod["id"], "qty": "100", "unit_price": "80"}],
        },
    )
    inc_recs = client.get("/api/v1/recommendations?days=14", headers=h_inc).json()
    assert inc_recs["incomplete_data"] is True
    assert len(inc_recs["recommendations"]) == 1
    assert inc_recs["recommendations"][0]["code"] == "SET_OPENING_CASH"
    assert inc_recs["recommendations"][0]["suggested_scenario"] is None

    # 2. Healthy no-gap business -> empty list []
    h_ok = _setup_merchant(client, "healthy@example.com", "1000")
    client.post(
        "/api/v1/cash/opening",
        headers=h_ok,
        json={"amount": "50000", "date": (today - dt.timedelta(days=20)).isoformat()},
    )
    ok_recs = client.get("/api/v1/recommendations?days=14", headers=h_ok).json()
    assert ok_recs["recommendations"] == []

    # 3. Gap > internal capital AND slow stock without scheduled reorder -> shortfall stated, suggested_scenario=None
    h_short = _setup_merchant(client, "shortfall@example.com", "5000")
    sup_s = client.post("/api/v1/suppliers", headers=h_short, json={"name": "Big Sup"}).json()
    prod_s = client.post(
        "/api/v1/products",
        headers=h_short,
        json={"name": "Luxury Tea", "sku": "TEA-9", "sale_price": "1000"},
    ).json()
    client.post(
        "/api/v1/cash/opening",
        headers=h_short,
        json={"amount": "10000", "date": (today - dt.timedelta(days=20)).isoformat()},
    )
    client.post(
        "/api/v1/inventory/opening",
        headers=h_short,
        json={
            "product_id": prod_s["id"],
            "qty": "5",
            "unit_cost": "400",
            "date": (today - dt.timedelta(days=20)).isoformat(),
        },
    )
    # 25,000 unpaid credit expense (slow stock stays 2,000 < 20,000 reserve gap -> 18,000 shortfall)
    client.post(
        "/api/v1/transactions",
        headers=h_short,
        json={
            "type": "expense",
            "supplier_id": sup_s["id"],
            "date": (today - dt.timedelta(days=5)).isoformat(),
            "due_date": (today + dt.timedelta(days=4)).isoformat(),
            "expense_amount": "25000",
            "paid_amount": "0",
            "notes": "Equipment bill",
        },
    )
    short_recs = client.get("/api/v1/recommendations?days=14", headers=h_short).json()["recommendations"]
    slow_cards = [r for r in short_recs if r["code"] == "RELEASE_SLOW_STOCK"]
    assert len(slow_cards) == 1
    assert slow_cards[0]["suggested_scenario"] is None
    assert slow_cards[0]["estimated_impact"] == "not quantifiable"
    assert "shortfall" in slow_cards[0]["evidence"].lower()
    assert "loan" not in slow_cards[0]["suggested_action"].lower()
    # Only one payable card (no duplicate cards for Big Sup)
    payable_cards = [r for r in short_recs if r["code"] == "DELAY_LARGE_PAYABLE"]
    assert len(payable_cards) == 1
