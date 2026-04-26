from __future__ import annotations

import logging
import time

from .config import get_settings
from .downloader import run_download_job
from .jobs import JobManager
from .models import JobState
from .redis_store import RedisJobStore
from .storage import ensure_directory

logger = logging.getLogger("sbaradio-ytdlp.worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    redis_store = RedisJobStore(
        settings.redis_connection_url,
        namespace=settings.redis_namespace,
        lock_ttl_seconds=settings.redis_job_lock_ttl_seconds,
        socket_timeout_seconds=settings.redis_healthcheck_timeout_seconds,
    )
    if not redis_store.enabled:
        raise SystemExit("APP_REDIS_URL is required for the worker.")

    ensure_directory(settings.temp_root)
    manager = JobManager(settings.temp_root, settings.max_active_jobs, settings.admin_history_limit, redis_store)
    logger.info("Worker started")

    while True:
        try:
            job_id = redis_store.dequeue_job_id(timeout_seconds=5)
            if job_id is None:
                continue

            job = manager.get(job_id)
            if job is None:
                logger.warning("Skipping missing job %s", job_id)
                continue
            if job.status in {JobState.ready, JobState.failed, JobState.cancelled}:
                logger.info("Skipping terminal job %s (%s)", job.id, job.status.value)
                continue
            if not redis_store.reserve_active_slot(job.id, settings.max_active_jobs):
                redis_store.enqueue_job(job.id)
                time.sleep(1)
                continue

            logger.info("Starting job %s", job.id)
            try:
                run_download_job(job, manager, settings)
            finally:
                redis_store.release_active_slot(job.id)
                logger.info("Finished job %s with status %s", job.id, job.status.value)
        except Exception:
            logger.exception("Worker loop error")
            time.sleep(2)


if __name__ == "__main__":
    main()
