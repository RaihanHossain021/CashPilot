import datetime as dt
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import InventoryMovement
from app.seed import GROCERY_DEMO_EMAIL, GROCERY_DEMO_PASSWORD, seed_grocery_demo
from app.services import finance

AS_OF = dt.date(2026, 11, 28)


def _create_biz(client: TestClient, email: str, name: str) -> tuple[dict[str, str], uuid.UUID]:
    token = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password1234", "name": name},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    biz = client.post(
        "/api/v1/business",
        headers=headers,
        json={
            "name": f"{name} Biz",
            "vertical": "grocery",
            "currency": "BDT",
            "min_cash_reserve": "1000.00",
            "slow_stock_days_threshold": 45,
        },
    ).json()
    return headers, uuid.UUID(biz["id"])


def test_seeded_grocery_finance_metrics_and_invariants(
    client: TestClient, db_session: Session
) -> None:
    seed_info = seed_grocery_demo(db_session, today=AS_OF)
    db_session.commit()
    biz_id = uuid.UUID(seed_info["business_id"])

    token = client.post(
        "/api/v1/auth/login",
        json={"email": GROCERY_DEMO_EMAIL, "password": GROCERY_DEMO_PASSWORD},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    cash = finance.get_cash_position(db_session, biz_id, as_of=AS_OF)
    assert cash["cash_on_hand"] == Decimal("70000.0000")
    assert cash["opening_cash_set"] is True
    assert cash["incomplete_data"] is False

    rec = finance.get_receivables(db_session, biz_id, as_of=AS_OF)
    assert rec["total"] == Decimal("40000.0000")
    assert rec["overdue_amount"] == Decimal("40000.0000")
    assert rec["overdue_count"] == 2

    pay = finance.get_payables(db_session, biz_id, as_of=AS_OF)
    assert pay["total"] == Decimal("90000.0000")
    assert pay["overdue_amount"] == Decimal("0.0000")

    inv_res = client.get(f"/api/v1/inventory?as_of={AS_OF.isoformat()}", headers=headers)
    assert inv_res.status_code == 200
    inv = inv_res.json()
    assert inv["total_stock_value"] == "149290.0000"
    assert inv["slow_stock_value_flagged"] == "35000.0000"
    # Verify stock invariant matches sum(inventory_movements)
    for item in inv["items"]:
        mov_sum = db_session.query(func.sum(InventoryMovement.qty_delta)).filter(
            InventoryMovement.business_id == biz_id,
            InventoryMovement.product_id == uuid.UUID(item["product_id"]),
        ).scalar()
        assert Decimal(item["on_hand_qty"]) == Decimal(mov_sum)

    # Purchases (45,000 + 90,000) are NOT expenses; only rent (15,000) + wages (10,000) = 25,000
    prof_res = client.get(f"/api/v1/profitability?days=30&as_of={AS_OF.isoformat()}", headers=headers)
    assert prof_res.status_code == 200
    prof = prof_res.json()
    assert prof["expenses"] == "25000.0000"
    # Sales in last 30d: 25,000 + 20,000 + 14 * 6,000 = 129,000
    assert prof["net_sales"] == "129000.0000"


def test_short_history_velocity_fresh_stock_and_due_today_boundary(
    client: TestClient, db_session: Session
) -> None:
    headers, biz_id = _create_biz(client, "edge@example.com", "Edge Owner")

    cust = client.post("/api/v1/customers", headers=headers, json={"name": "Cust"}).json()
    sup = client.post("/api/v1/suppliers", headers=headers, json={"name": "Sup"}).json()
    # Active item opened 10 days ago (history_days = 10), sold 5 units -> velocity = 5/10 = 0.5/day, DOS = 10
    p_fast = client.post(
        "/api/v1/products",
        headers=headers,
        json={"name": "Fast Milk", "sku": "MILK-1", "sale_price": "100.00"},
    ).json()
    # Freshly received item 2 days ago with 0 sales -> must NOT be flagged slow
    p_fresh = client.post(
        "/api/v1/products",
        headers=headers,
        json={"name": "Fresh Cheese", "sku": "CHEESE-1", "sale_price": "500.00"},
    ).json()

    day_minus_9 = AS_OF - dt.timedelta(days=9)  # inclusive 10-day span
    client.post(
        "/api/v1/inventory/opening",
        headers=headers,
        json={"product_id": p_fast["id"], "qty": "10", "unit_cost": "60.00", "date": day_minus_9.isoformat()},
    )
    client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "purchase",
            "supplier_id": sup["id"],
            "date": (AS_OF - dt.timedelta(days=2)).isoformat(),
            "paid_amount": "1000.00",
            "items": [{"product_id": p_fresh["id"], "qty": "5", "unit_price": "200.00"}],
        },
    )
    # Sale due EXACTLY on AS_OF -> overdue boundary due_date <= as_of
    client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "sale",
            "customer_id": cust["id"],
            "date": (AS_OF - dt.timedelta(days=5)).isoformat(),
            "due_date": AS_OF.isoformat(),
            "paid_amount": "0",
            "items": [{"product_id": p_fast["id"], "qty": "5"}],
        },
    )

    # Opening cash missing -> incomplete_data = True
    cash_no_open = finance.get_cash_position(db_session, biz_id, as_of=AS_OF)
    assert cash_no_open["incomplete_data"] is True

    # Due today counts as overdue
    rec = finance.get_receivables(db_session, biz_id, as_of=AS_OF)
    assert rec["total"] == Decimal("500.0000")
    assert rec["overdue_amount"] == Decimal("500.0000")
    # Historical as_of before the sale date returns 0 receivables
    rec_before = finance.get_receivables(db_session, biz_id, as_of=day_minus_9)
    assert rec_before["total"] == Decimal("0.0000")

    inv = finance.get_inventory_insights(db_session, biz_id, as_of=AS_OF)
    assert inv.velocity_window_days == 10
    by_sku = {i.sku: i for i in inv.items}
    assert by_sku["MILK-1"].daily_velocity == Decimal("0.5000")
    assert by_sku["MILK-1"].days_of_stock == Decimal("10.0000")
    assert by_sku["MILK-1"].slow_stock is False
    assert by_sku["CHEESE-1"].slow_stock is False
    assert inv.slow_stock_value_flagged == Decimal("0.0000")


def test_return_exceeding_balance_does_not_produce_negative_receivable(
    client: TestClient, db_session: Session
) -> None:
    headers, biz_id = _create_biz(client, "negrec@example.com", "Neg Rec Owner")
    cust = client.post("/api/v1/customers", headers=headers, json={"name": "Buyer"}).json()
    prod = client.post(
        "/api/v1/products",
        headers=headers,
        json={"name": "Widget", "sku": "W-1", "sale_price": "200.00"},
    ).json()
    client.post(
        "/api/v1/inventory/opening",
        headers=headers,
        json={"product_id": prod["id"], "qty": "10", "unit_cost": "100.00", "date": "2026-11-01"},
    )

    # Sale 1000, paid 800 -> balance_due = 200
    sale = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "sale",
            "customer_id": cust["id"],
            "date": "2026-11-05",
            "due_date": "2026-11-20",
            "paid_amount": "800.00",
            "items": [{"product_id": prod["id"], "qty": "5"}],
        },
    ).json()

    # Return 600 (3 units): clears 200 balance and auto-refunds 400 cash
    ret = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "sale_return",
            "original_transaction_id": sale["id"],
            "date": "2026-11-10",
            "items": [{"product_id": prod["id"], "qty": "3"}],
        },
    )
    assert ret.status_code == 201
    assert ret.json()["amount_paid"] == "400.0000"

    rec = finance.get_receivables(db_session, biz_id, as_of=dt.date(2026, 11, 15))
    assert rec["total"] == Decimal("0.0000")

    prof = finance.get_profitability(db_session, biz_id, days=30, as_of=dt.date(2026, 11, 15))
    # Net sales = 1000 - 600 = 400; COGS = 5*100 - 3*100 = 200; Gross profit = 200 (50%)
    assert prof.net_sales == Decimal("400.0000")
    assert prof.cogs == Decimal("200.0000")
    assert prof.gross_profit == Decimal("200.0000")
    assert prof.gross_margin_pct == Decimal("50.0000")
