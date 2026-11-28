import datetime as dt
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import CashMovement, InventoryMovement, Product, Transaction, TransactionItem


def _setup_business(client: TestClient, email: str, name: str) -> tuple[str, dict]:
    token = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password1234", "name": name},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    biz = client.post(
        "/api/v1/business",
        headers=headers,
        json={"name": f"{name} Biz", "vertical": "grocery", "currency": "BDT", "min_cash_reserve": "15000"},
    ).json()
    return token, {"headers": headers, "business": biz}


def test_weighted_average_cogs_snapshot_and_sale_flow(client: TestClient, db_session: Session) -> None:
    _, ctx = _setup_business(client, "avg@example.com", "Avg Owner")
    headers = ctx["headers"]

    sup = client.post("/api/v1/suppliers", headers=headers, json={"name": "Grain Co"}).json()
    cust = client.post("/api/v1/customers", headers=headers, json={"name": "Walk-In"}).json()
    prod = client.post(
        "/api/v1/products",
        headers=headers,
        json={"name": "Basmati Rice", "sku": "RICE-1", "sale_price": "100.00", "avg_cost": "0.00"},
    ).json()

    # Opening cash upsert: calling twice must replace, not double-count.
    client.post(
        "/api/v1/cash/opening",
        headers=headers,
        json={"amount": "10000.00", "date": "2026-11-01"},
    )
    upserted = client.post(
        "/api/v1/cash/opening",
        headers=headers,
        json={"amount": "5000.00", "date": "2026-11-01"},
    )
    assert upserted.status_code == 200

    # Purchase 1: 10 units @ 50.00 -> avg_cost = 50.0000
    p1 = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "purchase",
            "supplier_id": sup["id"],
            "date": "2026-11-02",
            "paid_amount": "500.00",
            "items": [{"product_id": prod["id"], "qty": "10", "unit_price": "50.00"}],
        },
    )
    assert p1.status_code == 201
    assert p1.json()["balance_due"] == "0.0000"

    # Purchase 2 (credit): 5 units @ 80.00 -> avg_cost = (10*50 + 5*80) / 15 = 900 / 15 = 60.0000
    p2 = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "purchase",
            "supplier_id": sup["id"],
            "date": "2026-11-03",
            "paid_amount": "0",
            "items": [{"product_id": prod["id"], "qty": "5", "unit_price": "80.00"}],
        },
    )
    assert p2.status_code == 201
    assert p2.json()["due_date"] == "2026-12-03"  # default +30 days
    assert p2.json()["balance_due"] == "400.0000"

    db_prod = db_session.get(Product, prod["id"])
    assert db_prod is not None
    assert db_prod.avg_cost == Decimal("60.0000")

    # Sale of 4 units with unit_price defaulted from product.sale_price (100.00) and header discount 50
    s1 = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "sale",
            "customer_id": cust["id"],
            "date": "2026-11-04",
            "discount": "50.00",
            "paid_amount": "200.00",
            "items": [{"product_id": prod["id"], "qty": "4"}],
        },
    )
    assert s1.status_code == 201
    s1_data = s1.json()
    assert s1_data["total"] == "350.0000"
    assert s1_data["balance_due"] == "150.0000"
    assert s1_data["due_date"] == "2026-11-18"  # default +14 days
    assert s1_data["items"][0]["unit_cost_snapshot"] == "60.0000"

    # Later purchase at higher cost (120.00) changes avg_cost, NOT prior sale's COGS snapshot!
    p3 = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "purchase",
            "supplier_id": sup["id"],
            "date": "2026-11-05",
            "paid_amount": "0",
            "items": [{"product_id": prod["id"], "qty": "11", "unit_price": "120.00"}],
        },
    )
    assert p3.status_code == 201
    # On hand before p3 = 15 - 4 = 11 @ 60.0000; + 11 @ 120.0000 -> avg_cost = 90.0000
    db_session.refresh(db_prod)
    assert db_prod.avg_cost == Decimal("90.0000")

    s1_item = db_session.query(TransactionItem).filter(TransactionItem.transaction_id == s1_data["id"]).one()
    assert s1_item.unit_cost_snapshot == Decimal("60.0000")

    # Verify invariants: cash = sum(cash_movements), stock = sum(inventory_movements)
    biz_id = ctx["business"]["id"]
    total_cash = db_session.query(func.sum(CashMovement.signed_amount)).filter(CashMovement.business_id == biz_id).scalar()
    # 5000 opening - 500 p1 + 200 s1 = 4700
    assert total_cash == Decimal("4700.0000")

    total_stock = db_session.query(func.sum(InventoryMovement.qty_delta)).filter(InventoryMovement.business_id == biz_id).scalar()
    # +10 +5 -4 +11 = 22
    assert total_stock == Decimal("22.0000")


def test_payments_idempotency_overpayment_and_returns(client: TestClient, db_session: Session) -> None:
    _, ctx = _setup_business(client, "ret@example.com", "Return Owner")
    headers = ctx["headers"]

    sup = client.post("/api/v1/suppliers", headers=headers, json={"name": "Sup"}).json()
    cust = client.post("/api/v1/customers", headers=headers, json={"name": "Cust"}).json()
    prod = client.post(
        "/api/v1/products",
        headers=headers,
        json={"name": "Cooking Oil", "sku": "OIL-1", "sale_price": "200.00"},
    ).json()

    client.post(
        "/api/v1/inventory/opening",
        headers=headers,
        json={"product_id": prod["id"], "qty": "10", "unit_cost": "140.00"},
    )

    # Idempotent transaction creation with initial payment
    sale_payload = {
        "type": "sale",
        "customer_id": cust["id"],
        "date": "2026-11-10",
        "paid_amount": "300.00",
        "idempotency_key": "sale-100",
        "items": [{"product_id": prod["id"], "qty": "3"}],
    }
    first = client.post("/api/v1/transactions", headers=headers, json=sale_payload)
    second = client.post("/api/v1/transactions", headers=headers, json=sale_payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["balance_due"] == "300.0000"  # 600 - 300

    sale_id = first.json()["id"]

    # Partial payment idempotency
    pay_res1 = client.post(
        f"/api/v1/transactions/{sale_id}/payments",
        headers=headers,
        json={"amount": "100.00", "date": "2026-11-11", "idempotency_key": "pay-1"},
    )
    pay_res2 = client.post(
        f"/api/v1/transactions/{sale_id}/payments",
        headers=headers,
        json={"amount": "100.00", "date": "2026-11-11", "idempotency_key": "pay-1"},
    )
    assert pay_res1.status_code == 201
    assert pay_res1.json()["id"] == pay_res2.json()["id"]
    assert pay_res1.json()["signed_amount"] == "100.0000"

    # Overpayment rejected with 409 (remaining balance is 200.00)
    overpay = client.post(
        f"/api/v1/transactions/{sale_id}/payments",
        headers=headers,
        json={"amount": "250.00", "date": "2026-11-11", "idempotency_key": "pay-over"},
    )
    assert overpay.status_code == 409

    # Purchase at different cost to change avg_cost before return, to verify return uses original snapshot (140)
    client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "purchase",
            "supplier_id": sup["id"],
            "date": "2026-11-11",
            "paid_amount": "0",
            "items": [{"product_id": prod["id"], "qty": "3", "unit_price": "200.00"}],
        },
    )
    db_prod = db_session.get(Product, prod["id"])
    assert db_prod is not None
    avg_before_return = db_prod.avg_cost

    # Return 2 units (400.00): 200.00 reduces remaining balance to 0, 200.00 auto-refunded as cash!
    ret = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "sale_return",
            "original_transaction_id": sale_id,
            "date": "2026-11-12",
            "items": [{"product_id": prod["id"], "qty": "2"}],
        },
    )
    assert ret.status_code == 201
    ret_data = ret.json()
    assert ret_data["total"] == "400.0000"
    assert ret_data["amount_paid"] == "200.0000"  # auto-refunded cash
    assert ret_data["balance_due"] == "0.0000"
    assert ret_data["items"][0]["unit_cost_snapshot"] == "140.0000"

    # avg_cost unchanged on return
    db_session.refresh(db_prod)
    assert db_prod.avg_cost == avg_before_return

    # Payments are disallowed on return transactions
    pay_on_return = client.post(
        f"/api/v1/transactions/{ret_data['id']}/payments",
        headers=headers,
        json={"amount": "10.00", "date": "2026-11-12", "idempotency_key": "pay-ret"},
    )
    assert pay_on_return.status_code == 422

    # Returning 2 more units (already returned 2 of 3) must fail 422
    over_ret = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "sale_return",
            "original_transaction_id": sale_id,
            "date": "2026-11-12",
            "items": [{"product_id": prod["id"], "qty": "2"}],
        },
    )
    assert over_ret.status_code == 422

    # List transactions check: original sale now has balance_due = 0.0000
    tx_list = client.get("/api/v1/transactions?type=sale", headers=headers).json()
    assert len(tx_list) == 1
    assert tx_list[0]["balance_due"] == "0.0000"
    assert tx_list[0]["returns_total"] == "400.0000"


def test_rollback_on_insufficient_stock_and_validation_guards(client: TestClient, db_session: Session) -> None:
    _, ctx_a = _setup_business(client, "rb_a@example.com", "Owner A")
    _, ctx_b = _setup_business(client, "rb_b@example.com", "Owner B")
    headers_a = ctx_a["headers"]
    headers_b = ctx_b["headers"]

    cust_a = client.post("/api/v1/customers", headers=headers_a, json={"name": "Cust A"}).json()
    prod_1 = client.post(
        "/api/v1/products",
        headers=headers_a,
        json={"name": "Item 1", "sku": "I-1", "sale_price": "50"},
    ).json()
    prod_2 = client.post(
        "/api/v1/products",
        headers=headers_a,
        json={"name": "Item 2", "sku": "I-2", "sale_price": "80"},
    ).json()
    client.post(
        "/api/v1/inventory/opening",
        headers=headers_a,
        json={"product_id": prod_1["id"], "qty": "5", "unit_cost": "30"},
    )
    client.post(
        "/api/v1/inventory/opening",
        headers=headers_a,
        json={"product_id": prod_2["id"], "qty": "1", "unit_cost": "40"},
    )

    # Item 1 has enough stock, item 2 fails -> whole transaction must roll back cleanly!
    failed = client.post(
        "/api/v1/transactions",
        headers=headers_a,
        json={
            "type": "sale",
            "customer_id": cust_a["id"],
            "date": "2026-11-15",
            "paid_amount": "50.00",
            "items": [
                {"product_id": prod_1["id"], "qty": "2"},
                {"product_id": prod_2["id"], "qty": "3"},
            ],
        },
    )
    assert failed.status_code == 409
    biz_a_id = ctx_a["business"]["id"]
    assert db_session.query(Transaction).filter(Transaction.business_id == biz_a_id).count() == 0
    assert db_session.query(TransactionItem).count() == 0
    assert db_session.query(CashMovement).filter(CashMovement.business_id == biz_a_id).count() == 0
    # Only the 2 opening stock movements remain
    assert db_session.query(InventoryMovement).filter(InventoryMovement.business_id == biz_a_id).count() == 2

    # Credit sale without customer_id -> 422
    no_cust = client.post(
        "/api/v1/transactions",
        headers=headers_a,
        json={
            "type": "sale",
            "date": "2026-11-15",
            "paid_amount": "0",
            "items": [{"product_id": prod_1["id"], "qty": "1"}],
        },
    )
    assert no_cust.status_code == 422

    # Cross-tenant customer/product/transaction -> 404
    cross = client.post(
        "/api/v1/transactions",
        headers=headers_b,
        json={
            "type": "sale",
            "customer_id": cust_a["id"],
            "date": "2026-11-15",
            "paid_amount": "10",
            "items": [{"product_id": prod_1["id"], "qty": "1"}],
        },
    )
    assert cross.status_code == 404


def test_partial_supplier_payment_and_expense(client: TestClient) -> None:
    _, ctx = _setup_business(client, "sup_pay@example.com", "Sup Pay Owner")
    headers = ctx["headers"]

    sup = client.post("/api/v1/suppliers", headers=headers, json={"name": "Wholesale Ltd"}).json()
    prod = client.post(
        "/api/v1/products",
        headers=headers,
        json={"name": "Tea", "sku": "TEA-1", "sale_price": "100"},
    ).json()

    purchase = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "purchase",
            "supplier_id": sup["id"],
            "date": "2026-11-10",
            "paid_amount": "0",
            "items": [{"product_id": prod["id"], "qty": "10", "unit_price": "50.00"}],
        },
    )
    assert purchase.status_code == 201
    p_id = purchase.json()["id"]
    assert purchase.json()["balance_due"] == "500.0000"

    pay = client.post(
        f"/api/v1/transactions/{p_id}/payments",
        headers=headers,
        json={"amount": "200.00", "date": "2026-11-12", "idempotency_key": "sup-pay-1"},
    )
    assert pay.status_code == 201
    assert pay.json()["signed_amount"] == "-200.0000"

    tx_after = client.get("/api/v1/transactions?type=purchase", headers=headers).json()
    assert tx_after[0]["amount_paid"] == "200.0000"
    assert tx_after[0]["balance_due"] == "300.0000"

    exp = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "type": "expense",
            "date": "2026-11-13",
            "expense_amount": "150.00",
            "paid_amount": "150.00",
            "notes": "Electricity",
        },
    )
    assert exp.status_code == 201
    assert exp.json()["total"] == "150.0000"
    assert exp.json()["balance_due"] == "0.0000"

