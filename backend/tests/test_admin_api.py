from fastapi.testclient import TestClient

from app.main import app, admin_state, settings


def admin_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/admin/login", json={"password": settings.admin_password}, headers={"X-Forwarded-For": "198.51.100.10"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}", "X-Forwarded-For": "198.51.100.10"}


def test_admin_summary_requires_login():
    client = TestClient(app)

    response = client.get("/api/admin/summary")

    assert response.status_code == 401


def test_admin_summary_reports_unique_visitors(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "temp_root", tmp_path)
    client = TestClient(app)
    headers = admin_headers(client)

    client.get("/api/health", headers={"X-Forwarded-For": "203.0.113.4", "User-Agent": "browser-a"})
    client.get("/api/health/live", headers={"X-Forwarded-For": "203.0.113.4", "User-Agent": "browser-a"})

    response = client.get("/api/admin/summary", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    matching_visitors = [visitor for visitor in payload["visitors"] if visitor["ip"] == "203.0.113.4"]
    assert len(matching_visitors) == 1
    assert matching_visitors[0]["requestCount"] >= 2
    assert payload["disk"]["tempRoot"] == str(tmp_path)


def test_admin_can_block_and_unblock_ip():
    client = TestClient(app)
    headers = admin_headers(client)
    blocked_ip = "203.0.113.99"

    try:
        block_response = client.post("/api/admin/blocked-ips", json={"ip": blocked_ip}, headers=headers)
        assert block_response.status_code == 200
        assert blocked_ip in block_response.json()["blockedIps"]

        blocked_response = client.get("/api/health", headers={"X-Forwarded-For": blocked_ip})
        assert blocked_response.status_code == 403
    finally:
        admin_state.unblock_ip(blocked_ip)

    allowed_response = client.get("/api/health", headers={"X-Forwarded-For": blocked_ip})
    assert allowed_response.status_code == 200


def test_admin_cleanup_removes_non_active_temp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "temp_root", tmp_path)
    temp_dir = tmp_path / "old-job"
    temp_dir.mkdir(parents=True)
    (temp_dir / "old.mp4").write_text("media", encoding="utf-8")

    client = TestClient(app)
    headers = admin_headers(client)

    response = client.post("/api/admin/temp/cleanup", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["removedFiles"] == 1
    assert payload["removedBytes"] == 5
    assert not temp_dir.exists()
