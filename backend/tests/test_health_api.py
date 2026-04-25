from fastapi.testclient import TestClient

from app.main import app, settings


def test_health_reports_readiness_details(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "temp_root", tmp_path)
    monkeypatch.setattr(settings, "redis_url", "")
    client = TestClient(app)

    response = client.get("/api/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["activeJobs"] >= 0
    assert payload["maxActiveJobs"] == settings.max_active_jobs
    assert payload["uptimeSeconds"] >= 0
    assert payload["checks"]["tempRoot"]["ok"] is True
    assert payload["checks"]["redis"]["ok"] is True
