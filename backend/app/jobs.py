from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from .models import JobState, JobStatusResponse, MediaKind, utc_now
from .redis_store import OptionalRedisJobStore


@dataclass
class Job:
    id: str
    url: str
    kind: MediaKind
    quality: str
    entry_ids: list[str]
    temp_dir: Path
    media_title: Optional[str] = None
    device_id: Optional[str] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    status: JobState = JobState.queued
    progress: float = 0
    current_item: Optional[str] = None
    total_items: int = 0
    completed_items: int = 0
    message: Optional[str] = "Queued"
    error: Optional[str] = None
    output_path: Optional[Path] = None
    is_archive: bool = False
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_response(self, cleanup_after_seconds: int | None = None) -> JobStatusResponse:
        expires_at = None
        if cleanup_after_seconds is not None and self.status in {JobState.ready, JobState.failed, JobState.cancelled}:
            expires_at = self.updated_at + timedelta(seconds=cleanup_after_seconds)

        return JobStatusResponse(
            jobId=self.id,
            status=self.status,
            mediaKind=self.kind,
            quality=self.quality,
            mediaTitle=self.media_title,
            progress=round(max(0, min(100, self.progress)), 2),
            currentItem=self.current_item,
            totalItems=self.total_items,
            completedItems=self.completed_items,
            message=self.message,
            error=self.error,
            downloadUrl=f"/api/jobs/{self.id}/download" if self.output_path else None,
            isArchive=self.is_archive,
            createdAt=self.created_at,
            updatedAt=self.updated_at,
            expiresAt=expires_at,
        )


class JobManager:
    def __init__(
        self,
        temp_root: Path,
        max_active_jobs: int,
        history_limit: int = 200,
        redis_store: OptionalRedisJobStore = None,
    ) -> None:
        self.temp_root = temp_root
        self.max_active_jobs = max_active_jobs
        self.history_limit = history_limit
        self.redis_store = redis_store
        self._jobs: Dict[str, Job] = {}
        self._history: Dict[str, JobStatusResponse] = {}
        self._history_order: list[str] = []
        self._lock = threading.RLock()
        self._load_history_from_redis()

    def create(
        self,
        url: str,
        kind: MediaKind,
        quality: str,
        entry_ids: list[str],
        media_title: str | None = None,
        device_id: str | None = None,
    ) -> Job:
        job_id = uuid.uuid4().hex
        with self._lock:
            if self.active_count() >= self.max_active_jobs:
                raise RuntimeError("Another download is already running.")
            try:
                if self.redis_store and not self.redis_store.reserve_active_slot(job_id, self.max_active_jobs):
                    raise RuntimeError("Another download is already running.")
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(f"Redis is not reachable: {exc}") from exc

            job = Job(
                id=job_id,
                url=url,
                kind=kind,
                quality=quality,
                entry_ids=entry_ids,
                temp_dir=self.temp_root / job_id,
                media_title=media_title,
                device_id=device_id,
            )
            self._jobs[job_id] = job
            self._remember(job)
            return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def require(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def active_count(self) -> int:
        active_states = {JobState.queued, JobState.metadata, JobState.downloading, JobState.converting, JobState.archiving}
        return sum(1 for job in self._jobs.values() if job.status in active_states)

    def update(self, job: Job, **changes) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = utc_now()
            self._remember(job)
            self._sync_active_slot(job)

    def cancel(self, job_id: str) -> Optional[Job]:
        job = self.get(job_id)
        if job is None:
            return None
        job.cancel_event.set()
        self.update(job, status=JobState.cancelled, message="Cancelling")
        return job

    def remove(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job is not None:
                self._remember(job)
                self._release_active_slot(job.id)
            return job

    def all(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def history(self) -> list[JobStatusResponse]:
        with self._lock:
            return sorted(self._history.values(), key=lambda snapshot: snapshot.updatedAt, reverse=True)

    def _remember(self, job: Job) -> None:
        snapshot = job.to_response()
        if job.id not in self._history:
            self._history_order.append(job.id)
        self._history[job.id] = snapshot

        while len(self._history_order) > self.history_limit:
            oldest_id = self._history_order.pop(0)
            self._history.pop(oldest_id, None)

        if self.redis_store:
            try:
                self.redis_store.remember_job(snapshot, self.history_limit)
            except Exception:
                return

    def _load_history_from_redis(self) -> None:
        if not self.redis_store:
            return

        try:
            snapshots = self.redis_store.load_history(self.history_limit)
        except Exception:
            return

        for snapshot in reversed(snapshots):
            if snapshot.jobId not in self._history:
                self._history_order.append(snapshot.jobId)
            self._history[snapshot.jobId] = snapshot

    def _sync_active_slot(self, job: Job) -> None:
        if not self.redis_store:
            return

        active_states = {JobState.queued, JobState.metadata, JobState.downloading, JobState.converting, JobState.archiving}
        try:
            if job.status in active_states:
                self.redis_store.refresh_active_slot(job.id)
                return
            self.redis_store.release_active_slot(job.id)
        except Exception:
            return

    def _release_active_slot(self, job_id: str) -> None:
        if self.redis_store:
            try:
                self.redis_store.release_active_slot(job_id)
            except Exception:
                return
