from fastapi.testclient import TestClient

from app.main import app, admin_state, settings


def admin_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/admin/login",
        json={"password": settings.admin_password},
        headers={"X-Forwarded-For": "198.51.100.10", "X-Device-Id": "admin-device"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}", "X-Forwarded-For": "198.51.100.10", "X-Device-Id": "admin-device"}


def test_admin_summary_requires_login():
    client = TestClient(app)

    response = client.get("/api/admin/summary")

    assert response.status_code == 401


def test_admin_summary_reports_browser_devices_and_skips_service_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "temp_root", tmp_path)
    client = TestClient(app)
    headers = admin_headers(client)

    client.get("/api/health", headers={"X-Forwarded-For": "203.0.113.4", "User-Agent": "browser-a"})
    client.get("/api/health/live", headers={"X-Forwarded-For": "203.0.113.4", "User-Agent": "browser-a"})
    client.get("/api/health", headers={"X-Forwarded-For": "203.0.113.5", "User-Agent": "browser-b", "X-Device-Id": "device-a"})
    client.get("/api/health/live", headers={"X-Forwarded-For": "203.0.113.5", "User-Agent": "browser-b", "X-Device-Id": "device-a"})

    response = client.get("/api/admin/summary", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    service_devices = [device for device in payload["devices"] if device["lastIp"] == "203.0.113.4"]
    matching_devices = [device for device in payload["devices"] if device["deviceId"] == "device-a"]
    assert service_devices == []
    assert len(matching_devices) == 1
    assert matching_devices[0]["lastIp"] == "203.0.113.5"
    assert matching_devices[0]["requestCount"] >= 2
    assert payload["disk"]["tempRoot"] == str(tmp_path)


def test_admin_can_block_and_unblock_device():
    client = TestClient(app)
    headers = admin_headers(client)
    blocked_device = "blocked-device"

    try:
        block_response = client.post("/api/admin/blocked-devices", json={"deviceId": blocked_device}, headers=headers)
        assert block_response.status_code == 200
        assert blocked_device in block_response.json()["blockedDevices"]

        blocked_response = client.get("/api/health", headers={"X-Device-Id": blocked_device})
        assert blocked_response.status_code == 403
    finally:
        admin_state.unblock_device(blocked_device)

    allowed_response = client.get("/api/health", headers={"X-Device-Id": blocked_device})
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
