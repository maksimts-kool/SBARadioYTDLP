from fastapi.testclient import TestClient

from app.main import app, manager
from app.models import JobState, MediaKind
from app.storage import ensure_directory, remove_directory


def test_available_jobs_lists_only_ready_jobs_with_existing_files():
    client = TestClient(app)
    ready_job = manager.create("https://www.youtube.com/watch?v=ready", MediaKind.mp4, "best", [])
    manager.update(ready_job, status=JobState.ready)
    missing_file_job = manager.create("https://www.youtube.com/watch?v=missing", MediaKind.mp4, "best", [])

    try:
        ensure_directory(ready_job.temp_dir)
        output_path = ready_job.temp_dir / "ready.mp4"
        output_path.write_text("media", encoding="utf-8")
        manager.update(ready_job, output_path=output_path)
        manager.update(missing_file_job, status=JobState.ready, output_path=missing_file_job.temp_dir / "missing.mp4")

        response = client.get("/api/jobs/available")

        assert response.status_code == 200
        payload = response.json()
        assert [job["jobId"] for job in payload] == [ready_job.id]
        assert payload[0]["downloadUrl"] == f"/api/jobs/{ready_job.id}/download"
    finally:
        manager.remove(ready_job.id)
        manager.remove(missing_file_job.id)
        remove_directory(ready_job.temp_dir)
        remove_directory(missing_file_job.temp_dir)
