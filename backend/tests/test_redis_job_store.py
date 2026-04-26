from app.jobs import JobManager
from app.models import JobState, JobStatusResponse, MediaKind, utc_now


class FakeRedisJobStore:
    def __init__(self, reserve_result: bool = True, history: list[JobStatusResponse] | None = None) -> None:
        self.reserve_result = reserve_result
        self.history = history or []
        self.remembered: list[JobStatusResponse] = []
        self.refreshed: list[str] = []
        self.released: list[str] = []

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
