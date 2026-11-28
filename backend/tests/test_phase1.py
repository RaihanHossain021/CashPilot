import datetime as dt
import uuid
from decimal import Decimal

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Business, CashMovement, User


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_register_login_and_token_claims(client: TestClient) -> None:
    res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "Alice@Example.COM",
            "password": "strong-password-123",
            "name": "Alice Merchant",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "alice@example.com"

    decoded = jwt.decode(
        body["access_token"],
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    assert decoded["sub"] == body["user"]["id"]
    assert "business_id" not in decoded

    dup = client.post(
        "/api/v1/auth/register",
        json={
            "email": "alice@example.com",
            "password": "strong-password-123",
            "name": "Alice Again",
        },
    )
    assert dup.status_code == 409

    login_ok = client.post(
        "/api/v1/auth/login",
        json={"email": "  ALICE@example.com ", "password": "strong-password-123"},
    )
    assert login_ok.status_code == 200
    assert login_ok.json()["user"]["email"] == "alice@example.com"

    login_bad_pw = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "wrong-password"},
    )
    assert login_bad_pw.status_code == 401

    login_missing = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "strong-password-123"},
    )
    assert login_missing.status_code == 401


def test_business_onboarding_and_one_per_user(client: TestClient) -> None:
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner@example.com",
            "password": "strong-password-123",
            "name": "Shop Owner",
        },
    )
    token = reg.json()["access_token"]

    missing_biz = client.get("/api/v1/business", headers=_auth_headers(token))
    assert missing_biz.status_code == 404

    created = client.post(
        "/api/v1/business",
        headers=_auth_headers(token),
        json={
            "name": "Corner Mart",
            "vertical": "grocery",
            "currency": "BDT",
            "min_cash_reserve": "5000.00",
            "slow_stock_days_threshold": 45,
        },
    )
    assert created.status_code == 201
    biz = created.json()
    assert biz["name"] == "Corner Mart"
    assert biz["min_cash_reserve"] == "5000.0000"

    fetched = client.get("/api/v1/business", headers=_auth_headers(token))
    assert fetched.status_code == 200
    assert fetched.json()["id"] == biz["id"]

    second_biz = client.post(
        "/api/v1/business",
        headers=_auth_headers(token),
        json={"name": "Second Shop", "vertical": "service", "currency": "USD"},
    )
    assert second_biz.status_code == 409


def test_tenant_isolation_and_master_data(client: TestClient) -> None:
    token_a = client.post(
        "/api/v1/auth/register",
        json={"email": "a@example.com", "password": "password1234", "name": "Owner A"},
    ).json()["access_token"]
    token_b = client.post(
        "/api/v1/auth/register",
        json={"email": "b@example.com", "password": "password1234", "name": "Owner B"},
    ).json()["access_token"]

    biz_a = client.post(
        "/api/v1/business",
        headers=_auth_headers(token_a),
        json={"name": "Alpha Grocer", "vertical": "grocery", "currency": "USD"},
    ).json()
    biz_b = client.post(
        "/api/v1/business",
        headers=_auth_headers(token_b),
        json={"name": "Beta Services", "vertical": "service", "currency": "USD"},
    ).json()

    # Passing a spoofed business_id in body must not leak or override tenant A.
    cust_a = client.post(
        "/api/v1/customers",
        headers=_auth_headers(token_a),
        json={"name": "Customer A", "phone": "111", "business_id": biz_b["id"]},
    )
    assert cust_a.status_code == 201
    assert cust_a.json()["business_id"] == biz_a["id"]

    sup_b = client.post(
        "/api/v1/suppliers",
        headers=_auth_headers(token_b),
        json={"name": "Supplier B", "phone": "222"},
    )
    assert sup_b.status_code == 201
    assert sup_b.json()["business_id"] == biz_b["id"]

    prod_a = client.post(
        "/api/v1/products",
        headers=_auth_headers(token_a),
        json={
            "name": "Rice 5kg",
            "sku": "RICE-5",
            "kind": "goods",
            "unit": "bag",
            "sale_price": "12.50",
            "avg_cost": "9.00",
        },
    )
    assert prod_a.status_code == 201
    assert prod_a.json()["sale_price"] == "12.5000"

    # Same SKU is rejected inside business A, but allowed inside business B.
    dup_sku_a = client.post(
        "/api/v1/products",
        headers=_auth_headers(token_a),
        json={"name": "Rice Duplicate", "sku": "RICE-5"},
    )
    assert dup_sku_a.status_code == 409

    prod_b = client.post(
        "/api/v1/products",
        headers=_auth_headers(token_b),
        json={"name": "Consulting Hour", "sku": "RICE-5", "kind": "service", "track_inventory": False},
    )
    assert prod_b.status_code == 201

    assert [c["name"] for c in client.get("/api/v1/customers", headers=_auth_headers(token_a)).json()] == [
        "Customer A"
    ]
    assert client.get("/api/v1/customers", headers=_auth_headers(token_b)).json() == []
    assert client.get("/api/v1/suppliers", headers=_auth_headers(token_a)).json() == []
    assert [s["name"] for s in client.get("/api/v1/suppliers", headers=_auth_headers(token_b)).json()] == [
        "Supplier B"
    ]
    assert [p["name"] for p in client.get("/api/v1/products", headers=_auth_headers(token_a)).json()] == [
        "Rice 5kg"
    ]
    assert [p["name"] for p in client.get("/api/v1/products", headers=_auth_headers(token_b)).json()] == [
        "Consulting Hour"
    ]


def test_cash_movement_partial_idempotency_index(db_session: Session) -> None:
    user = User(id=uuid.uuid4(), email="idem@example.com", password_hash="x", name="Idem")
    db_session.add(user)
    db_session.flush()
    biz = Business(id=uuid.uuid4(), owner_id=user.id, name="Idem Shop")
    db_session.add(biz)
    db_session.flush()

    today = dt.date.today()
    # Multiple NULL idempotency_key rows are allowed for the same business.
    db_session.add_all(
        [
            CashMovement(business_id=biz.id, date=today, signed_amount=Decimal("100.00")),
            CashMovement(business_id=biz.id, date=today, signed_amount=Decimal("200.00")),
        ]
    )
    db_session.commit()

    # Duplicate non-null (business_id, idempotency_key) must fail at DB level.
    db_session.add(
        CashMovement(
            business_id=biz.id,
            date=today,
            signed_amount=Decimal("50.00"),
            idempotency_key="pay-1",
        )
    )
    db_session.commit()

    db_session.add(
        CashMovement(
            business_id=biz.id,
            date=today,
            signed_amount=Decimal("50.00"),
            idempotency_key="pay-1",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
