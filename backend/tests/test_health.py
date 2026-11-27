from fastapi.testclient import TestClient

from app.main import app


def test_docs_available() -> None:
    client = TestClient(app)
    response = client.get("/docs")
    assert response.status_code == 200


def test_health_endpoint_reports_status(monkeypatch) -> None:
    monkeypatch.setattr("app.main.check_db_connection", lambda: (True, None))
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_health_endpoint_reports_db_error(monkeypatch) -> None:
    monkeypatch.setattr("app.main.check_db_connection", lambda: (False, "connection refused"))
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "database": "disconnected",
        "detail": "connection refused",
    }
