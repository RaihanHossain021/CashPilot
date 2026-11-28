import datetime as dt
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ScheduledEvent
from app.seed import GROCERY_DEMO_EMAIL, GROCERY_DEMO_PASSWORD
from app.services import forecast
from app.services.forecast import ExtraOutflowOverride, MoveOutflowOverride

AS_OF = dt.date(2026, 11, 28)


def _setup_user(client: TestClient, email: str) -> tuple[dict[str, str], uuid.UUID]:
    token = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password1234", "name": "Owner"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    biz = client.post(
        "/api/v1/business",
        headers=headers,
        json={"name": "Forecast Shop", "vertical": "grocery", "currency": "BDT", "min_cash_reserve": "2000.00"},
    ).json()
    return headers, uuid.UUID(biz["id"])


def test_seeded_7_vs_14_vs_30_day_consistency_and_daily_math(client: TestClient) -> None:
    client.post(f"/api/v1/dev/seed?today={AS_OF.isoformat()}")
    token = client.post(
        "/api/v1/auth/login",
        json={"email": GROCERY_DEMO_EMAIL, "password": GROCERY_DEMO_PASSWORD},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    f7 = client.get(f"/api/v1/cashflow/forecast?days=7&as_of={AS_OF.isoformat()}", headers=headers).json()
    f14 = client.get(f"/api/v1/cashflow/forecast?days=14&as_of={AS_OF.isoformat()}", headers=headers).json()
    f30 = client.get(f"/api/v1/cashflow/forecast?days=30&as_of={AS_OF.isoformat()}", headers=headers).json()

    # Shared days match identically across 7, 14, and 30 horizons
    assert f7["daily"] == f14["daily"][:7]
    assert f14["daily"] == f30["daily"][:14]

    # 7-day view misses the day-9 shortage; 14-day and 30-day catch it identically
    assert f7["estimated_cash_gap_vs_zero"] == "0.0000"
    assert f7["estimated_cash_gap_vs_reserve"] == "0.0000"
    assert f14["lowest_cash_amount"] == "-11000.0000"
    assert f30["lowest_cash_amount"] == "-11000.0000"
    assert f14["lowest_cash_date"] == f30["lowest_cash_date"]

    # Slow stock must NOT appear inside causes (it's unlockable capital)
    assert all(c["kind"] in ("outflow", "overdue_receivable") for c in f14["causes"])
    assert f14["unlockable_slow_stock_value"] == "35000.0000"

    # Accounting invariant: closing = opening + inflows - outflows for every day
    for day in f30["daily"]:
        expected_close = (
            Decimal(day["opening_cash"])
            + Decimal(day["confirmed_inflows"])
            + Decimal(day["expected_inflows"])
            + Decimal(day["estimated_inflows"])
            - Decimal(day["confirmed_outflows"])
            - Decimal(day["expected_outflows"])
            - Decimal(day["estimated_outflows"])
        )
        assert Decimal(day["closing_cash"]) == expected_close


def test_no_double_count_overdue_payable_day1_and_scheduled_events(
    client: TestClient, db_session: Session
) -> None:
    headers, biz_id = _setup_user(client, "nodup@example.com")
    cust = client.post("/api/v1/customers", headers=headers, json={"name": "Cust"}).json()
    sup = client.post("/api/v1/suppliers", headers=headers, json={"name": "Sup"}).json()
    prod = client.post(
        "/api/v1/products",
        headers=headers,
        json={"name": "Item", "sku": "IT-1", "sale_price": "100.00"},
    ).json()

    d_open = AS_OF - dt.timedelta(days=10)
    client.post(
        "/api/v1/cash/opening",
        headers=headers,
        json={"amount": "10000.00", "date": d_open.isoformat()},
    )
    client.post(
        "/api/v1/inventory/opening",
        headers=headers,
        json={"product_id": prod["id"], "qty": "20", "unit_cost": "50.00", "date": d_open.isoformat()},
    )

    # Credit sale created 8 days ago, partially paid 3 days ago (later settlement must NOT enter 14d same-day avg)
    sale = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "sale",
            "customer_id": cust["id"],
            "date": (AS_OF - dt.timedelta(days=8)).isoformat(),
            "due_date": (AS_OF + dt.timedelta(days=5)).isoformat(),
            "paid_amount": "0",
            "items": [{"product_id": prod["id"], "qty": "10"}],
        },
    ).json()
    client.post(
        f"/api/v1/transactions/{sale['id']}/payments",
        headers=headers,
        json={
            "amount": "400.00",
            "date": (AS_OF - dt.timedelta(days=3)).isoformat(),
            "idempotency_key": "late-settle-1",
        },
    )

    # Overdue supplier payable (due today == AS_OF) -> lands on Day 1 (AS_OF + 1)
    overdue_pur = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "purchase",
            "supplier_id": sup["id"],
            "date": (AS_OF - dt.timedelta(days=5)).isoformat(),
            "due_date": AS_OF.isoformat(),
            "paid_amount": "0",
            "items": [{"product_id": prod["id"], "qty": "5", "unit_price": "200.00"}],
        },
    ).json()
    # Partial payment of 300 on overdue purchase -> remaining 700 lands on Day 1, and payment is NOT in same-day avg
    client.post(
        f"/api/v1/transactions/{overdue_pur['id']}/payments",
        headers=headers,
        json={
            "amount": "300.00",
            "date": (AS_OF - dt.timedelta(days=1)).isoformat(),
            "idempotency_key": "sup-settle-1",
        },
    )

    # Manual scheduled events: 1 active past-due (lands Day 1), 1 completed (ignored), 1 cancelled (ignored)
    db_session.add_all(
        [
            ScheduledEvent(
                business_id=biz_id,
                direction="outflow",
                label="Past due rent",
                amount=Decimal("500.00"),
                expected_on=AS_OF - dt.timedelta(days=1),
                certainty="confirmed",
                status="active",
            ),
            ScheduledEvent(
                business_id=biz_id,
                direction="outflow",
                label="Old paid rent",
                amount=Decimal("999.00"),
                expected_on=AS_OF + dt.timedelta(days=2),
                certainty="confirmed",
                status="completed",
            ),
            ScheduledEvent(
                business_id=biz_id,
                direction="inflow",
                label="Cancelled grant",
                amount=Decimal("5000.00"),
                expected_on=AS_OF + dt.timedelta(days=2),
                certainty="expected",
                status="cancelled",
            ),
        ]
    )
    db_session.commit()

    f14 = forecast.build_forecast(db_session, biz_id, days=14, as_of=AS_OF)
    assert f14.limited_data is True  # 11 days of history < 14
    # Same-day operating inflows and outflows are both 0 (opening + later credit settlements excluded)
    assert f14.daily[0].estimated_inflows == Decimal("0.0000")
    assert f14.daily[0].estimated_outflows == Decimal("0.0000")
    # Day 1 confirmed outflows = remaining overdue payable (700) + active past-due scheduled event (500) = 1200
    assert f14.daily[0].confirmed_outflows == Decimal("1200.0000")
    # Day 5 expected inflow = remaining credit sale balance (1000 - 400 = 600)
    assert f14.daily[4].expected_inflows == Decimal("600.0000")
    # Day 2 ignores completed/cancelled scheduled events
    assert f14.daily[1].confirmed_outflows == Decimal("0.0000")
    assert f14.daily[1].expected_inflows == Decimal("0.0000")

    # Verify overrides are purely read-only in memory
    sim = forecast.build_forecast(
        db_session,
        biz_id,
        days=14,
        as_of=AS_OF,
        overrides=[
            MoveOutflowOverride(transaction_id=uuid.UUID(overdue_pur["id"]), delay_days=4),
            ExtraOutflowOverride(label="New shelf", amount=Decimal("2000.00"), on=AS_OF + dt.timedelta(days=3)),
        ],
    )
    assert sim.daily[0].confirmed_outflows == Decimal("500.0000")
    assert sim.daily[2].confirmed_outflows == Decimal("2000.0000")
    assert sim.daily[3].confirmed_outflows == Decimal("700.0000")
