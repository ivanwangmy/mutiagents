from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"


def test_system_info() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/system/info")
        assert resp.status_code == 200
        body = resp.json()
        assert body["app_name"] == "AI 智播课堂"
        assert body["database_backend"] in {"sqlite", "postgresql"}
        assert "task_token_budget" in body["limits"]


def test_config_status_does_not_leak_key() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/system/config-status")
        assert resp.status_code == 200
        body = resp.json()
        assert "api_key" not in resp.text.lower()
        assert body["provider"] == "deepseek"
        assert set(body["capabilities"]) >= {"text", "stream", "tool_calling", "structured_output"}
