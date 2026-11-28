import datetime as dt
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.advisor.tools import execute_tool
from app.models import CashMovement, InventoryMovement, ScheduledEvent, Transaction, TransactionItem
from app.seed import GROCERY_DEMO_EMAIL, GROCERY_DEMO_PASSWORD, seed_grocery_demo
from app.services import forecast


def _auth_headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _ledger_counts(db: Session, biz_id: uuid.UUID) -> tuple[int, int, int, int, int]:
    return (
        db.query(Transaction).filter(Transaction.business_id == biz_id).count(),
        db.query(TransactionItem).count(),
        db.query(CashMovement).filter(CashMovement.business_id == biz_id).count(),
        db.query(InventoryMovement).filter(InventoryMovement.business_id == biz_id).count(),
        db.query(ScheduledEvent).filter(ScheduledEvent.business_id == biz_id).count(),
    )


def test_scenarios_baseline_noop_delay_beyond_horizon_and_readonly(
    client: TestClient, db_session: Session
) -> None:
    today = dt.date.today()
    seed = seed_grocery_demo(db_session, today=today)
    db_session.commit()
    biz_id = uuid.UUID(seed["business_id"])
    headers = _auth_headers(client, GROCERY_DEMO_EMAIL, GROCERY_DEMO_PASSWORD)

    before_counts = _ledger_counts(db_session, biz_id)

    fc14 = client.get("/api/v1/cashflow/forecast?days=14", headers=headers).json()
    opts = client.get("/api/v1/scenarios/options", headers=headers).json()
    assert len(opts["receivables"]) == 2
    assert len(opts["payables"]) == 1
    assert len(opts["reorders"]) == 1
    assert "Karim Traders" in opts["receivables"][0]["label"]

    # 1. Delay Metro payable (due today + 9) by 7 days -> today + 16 (beyond 14d horizon!)
    metro_id = opts["payables"][0]["id"]
    delay_res = client.post(
        "/api/v1/scenarios",
        headers=headers,
        json={"type": "delay_payment", "horizon_days": 14, "transaction_id": metro_id, "delay_days": 7},
    )
    assert delay_res.status_code == 200
    delay_data = delay_res.json()
    assert delay_data["baseline"] == fc14
    assert delay_data["impact"]["moved_beyond_horizon"] is True
    assert "outside this period" in delay_data["impact"]["assumption_note"].lower()
    assert Decimal(delay_data["impact"]["cash_impact"]) > Decimal("0")

    # 2. 100% overdue dues collection eliminates the 14d reserve breach
    collect_res = client.post(
        "/api/v1/scenarios",
        headers=headers,
        json={"type": "collect_dues", "horizon_days": 14, "collect_pct": "100"},
    )
    assert collect_res.status_code == 200
    collect_data = collect_res.json()
    assert collect_data["simulated"]["estimated_cash_gap_vs_reserve"] == "0.0000"
    assert collect_data["impact"]["breach_days_change"] < 0
    for day in collect_data["simulated"]["daily"]:
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

    # 3. No-op build_forecast(overrides=[]) matches baseline
    assert forecast.build_forecast(db_session, biz_id, days=14, as_of=today, overrides=[]) == (
        forecast.build_forecast(db_session, biz_id, days=14, as_of=today)
    )

    # 4. Consistency: Advisor run_scenario tool and POST /scenarios match for 15,000 purchase
    buy_date = (today + dt.timedelta(days=3)).isoformat()
    api_buy = client.post(
        "/api/v1/scenarios",
        headers=headers,
        json={
            "type": "planned_purchase",
            "horizon_days": 14,
            "planned_purchase_amount": "15000",
            "planned_purchase_date": buy_date,
        },
    ).json()
    tool_buy = execute_tool(
        "run_scenario",
        {
            "type": "planned_purchase",
            "horizon_days": 14,
            "planned_purchase_amount": "15000",
            "planned_purchase_date": buy_date,
        },
        db_session,
        biz_id,
        today,
    )
    assert api_buy["simulated"]["lowest_cash_amount"] == tool_buy["simulated_lowest_cash"]
    assert api_buy["impact"]["cash_impact"] == tool_buy["cash_impact"]
    assert api_buy["impact"]["breach_days_change"] == tool_buy["breach_days_change"]
    assert Decimal(api_buy["impact"]["cash_impact"]) == Decimal("-15000.0000")
    assert api_buy["impact"]["affordable_above_reserve"] is False

    # Larger 65,000 purchase on day 3 breaches reserve early -> positive breach_days_change
    big_buy = client.post(
        "/api/v1/scenarios",
        headers=headers,
        json={
            "type": "planned_purchase",
            "horizon_days": 14,
            "planned_purchase_amount": "65000",
            "planned_purchase_date": buy_date,
        },
    ).json()
    assert big_buy["impact"]["breach_days_change"] > 0

    # 5. Strictly read-only: ledger row counts completely unchanged
    assert _ledger_counts(db_session, biz_id) == before_counts


def test_scenario_validation_wrong_type_and_cross_tenant(
    client: TestClient, db_session: Session
) -> None:
    today = dt.date.today()
    seed_grocery_demo(db_session, today=today)
    db_session.commit()
    headers = _auth_headers(client, GROCERY_DEMO_EMAIL, GROCERY_DEMO_PASSWORD)

    opts = client.get("/api/v1/scenarios/options", headers=headers).json()
    rec_id = opts["receivables"][0]["id"]
    pay_id = opts["payables"][0]["id"]

    # Validation: 0% rejected, delay_days > horizon rejected, out-of-horizon purchase rejected
    assert (
        client.post(
            "/api/v1/scenarios",
            headers=headers,
            json={"type": "collect_dues", "horizon_days": 14, "collect_pct": "0"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/scenarios",
            headers=headers,
            json={"type": "delay_payment", "horizon_days": 7, "delay_days": 10},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/scenarios",
            headers=headers,
            json={
                "type": "planned_purchase",
                "horizon_days": 7,
                "planned_purchase_amount": "1000",
                "planned_purchase_date": (today + dt.timedelta(days=10)).isoformat(),
            },
        ).status_code
        == 422
    )

    # Wrong target type -> 422
    assert (
        client.post(
            "/api/v1/scenarios",
            headers=headers,
            json={"type": "delay_payment", "horizon_days": 14, "transaction_id": rec_id, "delay_days": 5},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/scenarios",
            headers=headers,
            json={"type": "collect_dues", "horizon_days": 14, "transaction_id": pay_id, "collect_pct": "50"},
        ).status_code
        == 422
    )

    # Another business's target ID -> 404
    reg_b = client.post(
        "/api/v1/auth/register",
        json={"email": "other_sc@example.com", "password": "password1234", "name": "Other"},
    )
    headers_b = {"Authorization": f"Bearer {reg_b.json()['access_token']}"}
    client.post(
        "/api/v1/business",
        headers=headers_b,
        json={"name": "Other Shop", "vertical": "grocery", "currency": "BDT"},
    )
    assert (
        client.post(
            "/api/v1/scenarios",
            headers=headers_b,
            json={"type": "delay_payment", "horizon_days": 14, "transaction_id": pay_id, "delay_days": 5},
        ).status_code
        == 404
    )
