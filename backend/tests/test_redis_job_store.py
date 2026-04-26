from app.jobs import JobManager
from app.models import JobState, JobStatusResponse, MediaKind, utc_now


class FakeRedisJobStore:
    def __init__(self, reserve_result: bool = True, history: list[JobStatusResponse] | None = None) -> None:
        self.reserve_result = reserve_result
        self.history = history or []
        self.remembered: list[JobStatusResponse] = []
        self.refreshed: list[str] = []
        self.released: list[str] = []
        self.enqueued: list[str] = []
        self.payloads: dict[str, dict[str, object]] = {}
        self.deleted: list[str] = []

    def reserve_active_slot(self, job_id: str, max_active_jobs: int) -> bool:
        return self.reserve_result

    def refresh_active_slot(self, job_id: str) -> None:
        self.refreshed.append(job_id)

    def release_active_slot(self, job_id: str) -> None:
        self.released.append(job_id)

    def remember_job(self, snapshot: JobStatusResponse, history_limit: int) -> None:
        self.remembered.append(snapshot)

    def load_history(self, history_limit: int) -> list[JobStatusResponse]:
        return self.history[:history_limit]

    def enqueue_job(self, job_id: str) -> None:
        self.enqueued.append(job_id)

    def save_job_payload(self, payload: dict[str, object]) -> None:
        self.payloads[str(payload["id"])] = payload

    def load_job_payload(self, job_id: str) -> dict[str, object] | None:
        return self.payloads.get(job_id)

    def active_count(self) -> int:
        return len(self.refreshed) - len(self.released)

    def load_history_payloads(self, history_limit: int) -> list[dict[str, object]]:
        return list(self.payloads.values())[:history_limit]

    def is_cancel_requested(self, job_id: str) -> bool:
        payload = self.payloads.get(job_id)
        return payload is not None and payload.get("status") == JobState.cancelled.value

    def delete_job(self, job_id: str) -> None:
        self.deleted.append(job_id)
        self.payloads.pop(job_id, None)


def test_job_manager_uses_redis_for_active_capacity(tmp_path):
    redis_store = FakeRedisJobStore(reserve_result=False)
    manager = JobManager(tmp_path, max_active_jobs=1, redis_store=redis_store)

    try:
        manager.create("https://www.youtube.com/watch?v=abc12345678", MediaKind.mp4, "best", [])
    except RuntimeError as exc:
        assert str(exc) == "Another download is already running."
    else:
        raise AssertionError("Expected Redis capacity rejection")


def test_job_manager_refreshes_and_releases_redis_slots(tmp_path):
    redis_store = FakeRedisJobStore()
    manager = JobManager(tmp_path, max_active_jobs=1, redis_store=redis_store)

    job = manager.create("https://www.youtube.com/watch?v=abc12345678", MediaKind.mp4, "best", [])
    manager.update(job, status=JobState.downloading, progress=25)
    manager.update(job, status=JobState.ready, progress=100)

    assert job.id in redis_store.refreshed
    assert job.id in redis_store.released
    assert redis_store.remembered[-1].status == JobState.ready


def test_job_manager_loads_history_from_redis(tmp_path):
    snapshot = JobStatusResponse(
        jobId="stored-job",
        status=JobState.ready,
        mediaKind=MediaKind.mp3,
        quality="best",
        progress=100,
        totalItems=1,
        completedItems=1,
        message="Ready to download",
        isArchive=False,
        createdAt=utc_now(),
        updatedAt=utc_now(),
    )
    manager = JobManager(tmp_path, max_active_jobs=1, redis_store=FakeRedisJobStore(history=[snapshot]))

    assert manager.history()[0].jobId == "stored-job"


def test_job_manager_enqueues_and_loads_redis_job_payload(tmp_path):
    redis_store = FakeRedisJobStore()
    manager = JobManager(tmp_path, max_active_jobs=1, redis_store=redis_store)

    job = manager.create(
        "https://www.youtube.com/watch?v=abc12345678",
        MediaKind.mp4,
        "best",
        [],
        enforce_capacity=False,
        enqueue=True,
    )
    manager._jobs.clear()

    loaded = manager.get(job.id)

    assert redis_store.enqueued == [job.id]
    assert loaded is not None
    assert loaded.id == job.id
    assert loaded.cancel_check is not None


def test_job_manager_prefers_fresh_redis_payload_over_local_stale_job(tmp_path):
    redis_store = FakeRedisJobStore()
    manager = JobManager(tmp_path, max_active_jobs=1, redis_store=redis_store)

    job = manager.create("https://www.youtube.com/watch?v=abc12345678", MediaKind.mp4, "best", [], enforce_capacity=False)
    redis_store.payloads[job.id]["status"] = JobState.ready.value
    redis_store.payloads[job.id]["progress"] = 100
    redis_store.payloads[job.id]["message"] = "Ready to download"

    loaded = manager.get(job.id)

    assert loaded is not None
    assert loaded.status == JobState.ready
    assert loaded.progress == 100


def test_job_manager_remove_deletes_redis_payload(tmp_path):
    redis_store = FakeRedisJobStore()
    manager = JobManager(tmp_path, max_active_jobs=1, redis_store=redis_store)

    job = manager.create("https://www.youtube.com/watch?v=abc12345678", MediaKind.mp4, "best", [], enforce_capacity=False)
    removed = manager.remove(job.id)

    assert removed is not None
    assert redis_store.deleted == [job.id]
    assert redis_store.payloads == {}
