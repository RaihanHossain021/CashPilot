import datetime as dt
from decimal import Decimal

from fastapi.testclient import TestClient

from app.schemas import ForecastResponse, InventoryResponse
from app.seed import GROCERY_DEMO_EMAIL, GROCERY_DEMO_PASSWORD
from app.services.readiness import evaluate_readiness

AS_OF = dt.date(2026, 11, 28)


def _dummy_inventory(slow_pct: Decimal, slow_val: Decimal) -> InventoryResponse:
    return InventoryResponse(
        currency="BDT",
        as_of=AS_OF,
        velocity_window_days=14,
        slow_stock_days_threshold=45,
        total_stock_value=Decimal("100000.0000"),
        slow_stock_value_flagged=slow_val,
        slow_stock_pct_of_inventory=slow_pct,
        items=[],
    )


def _dummy_forecast(lowest_cash: Decimal, reserve: Decimal) -> ForecastResponse:
    gap_res = max(Decimal("0.0000"), reserve - lowest_cash)
    gap_zero = max(Decimal("0.0000"), -lowest_cash)
    return ForecastResponse(
        currency="BDT",
        as_of=AS_OF,
        horizon_days=14,
        limited_data=False,
        history_days=20,
        min_cash_reserve=reserve,
        lowest_cash_amount=lowest_cash,
        lowest_cash_date=AS_OF + dt.timedelta(days=5),
        estimated_cash_gap_vs_reserve=gap_res,
        estimated_cash_gap_vs_zero=gap_zero,
        gap_start_date=(AS_OF + dt.timedelta(days=5)) if gap_res > 0 else None,
        unlockable_slow_stock_value=Decimal("0.0000"),
        assumptions_note="test",
        causes=[],
        daily=[],
    )


def test_readiness_pure_thresholds_green_amber_red() -> None:
    reserve = Decimal("10000.0000")

    green = evaluate_readiness(
        currency="BDT",
        cash_position={"cash_on_hand": Decimal("16000.0000"), "min_cash_reserve": reserve},
        receivables={"total": Decimal("10000.0000"), "overdue_amount": Decimal("1000.0000")},
        inventory=_dummy_inventory(Decimal("5.0000"), Decimal("5000.0000")),
        coverage={"opening_cash_set": True, "history_days": 20, "tx_missing_due_date": 0},
        forecast=_dummy_forecast(Decimal("12000.0000"), reserve),
    )
    assert green.overall_status == "green"
    assert all(d.status == "green" for d in green.dimensions)

    amber = evaluate_readiness(
        currency="BDT",
        cash_position={"cash_on_hand": Decimal("12000.0000"), "min_cash_reserve": reserve},
        receivables={"total": Decimal("10000.0000"), "overdue_amount": Decimal("3000.0000")},
        inventory=_dummy_inventory(Decimal("15.0000"), Decimal("15000.0000")),
        coverage={"opening_cash_set": True, "history_days": 10, "tx_missing_due_date": 0},
        forecast=_dummy_forecast(Decimal("5000.0000"), reserve),
    )
    assert amber.overall_status == "amber"
    assert [d.status for d in amber.dimensions] == ["amber", "amber", "amber", "amber"]

    red = evaluate_readiness(
        currency="BDT",
        cash_position={"cash_on_hand": Decimal("8000.0000"), "min_cash_reserve": reserve},
        receivables={"total": Decimal("10000.0000"), "overdue_amount": Decimal("6000.0000")},
        inventory=_dummy_inventory(Decimal("30.0000"), Decimal("30000.0000")),
        coverage={"opening_cash_set": False, "history_days": 5, "tx_missing_due_date": 2},
        forecast=_dummy_forecast(Decimal("-2000.0000"), reserve),
    )
    assert red.overall_status == "red"
    assert [d.status for d in red.dimensions] == ["red", "red", "red", "red"]


def test_dashboard_readiness_parties_and_business_patch_on_seeded_grocery(
    client: TestClient,
) -> None:
    client.post(f"/api/v1/dev/seed?today={AS_OF.isoformat()}")
    token = client.post(
        "/api/v1/auth/login",
        json={"email": GROCERY_DEMO_EMAIL, "password": GROCERY_DEMO_PASSWORD},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    dash_res = client.get(f"/api/v1/dashboard?days=14&as_of={AS_OF.isoformat()}", headers=headers)
    assert dash_res.status_code == 200
    dash = dash_res.json()
    assert dash["cash_on_hand"] == "70000.0000"
    assert dash["customers_owe"] == "40000.0000"
    assert dash["overdue_receivables"] == "40000.0000"
    assert dash["we_owe_suppliers"] == "90000.0000"
    assert dash["slow_stock_value_flagged"] == "35000.0000"
    assert dash["estimated_cash_gap_vs_zero"] == "11000.0000"
    assert dash["estimated_cash_gap_vs_reserve"] == "26000.0000"
    assert dash["gap_date"] == (AS_OF + dt.timedelta(days=9)).isoformat()
    assert dash["incomplete_data"] is False

    # Readiness: projected_resilience and working_capital_efficiency (100% overdue) are red
    readiness = dash["readiness_summary"]
    assert readiness["overall_status"] == "red"
    by_key = {d["key"]: d for d in readiness["dimensions"]}
    assert by_key["record_completeness"]["status"] == "green"
    assert by_key["liquidity_buffer"]["status"] == "green"  # 70k >= 1.5 * 15k
    assert by_key["projected_resilience"]["status"] == "red"
    assert by_key["working_capital_efficiency"]["status"] == "red"

    # Internal-capital-first recommendations appear in priority order
    rec_codes = [r["code"] for r in dash["recommendations"]]
    assert rec_codes == [
        "COLLECT_OVERDUE_DUES",
        "RELEASE_SLOW_STOCK",
        "DELAY_LARGE_PAYABLE",
    ]

    # Standalone /readiness rejects 7-day alert blindness
    assert client.get("/api/v1/readiness?days=7", headers=headers).status_code == 422
    assert client.get(f"/api/v1/readiness?days=14&as_of={AS_OF.isoformat()}", headers=headers).status_code == 200

    # Parties balances endpoint returns computed dues without client math
    parties = client.get(f"/api/v1/parties/balances?as_of={AS_OF.isoformat()}", headers=headers).json()
    cust_map = {c["name"]: c for c in parties["customers"]}
    sup_map = {s["name"]: s for s in parties["suppliers"]}
    assert cust_map["Karim Traders"]["balance_due"] == "20000.0000"
    assert cust_map["Nadia Catering"]["overdue_amount"] == "20000.0000"
    assert sup_map["Metro Distribution"]["balance_due"] == "90000.0000"

    # Settings modal PATCH /business updates reserve
    patch = client.patch(
        "/api/v1/business",
        headers=headers,
        json={"min_cash_reserve": "20000.00"},
    )
    assert patch.status_code == 200
    assert patch.json()["min_cash_reserve"] == "20000.0000"
