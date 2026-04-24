from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .models import JobState, JobStatusResponse, MediaKind, utc_now


@dataclass
class Job:
    id: str
    url: str
    kind: MediaKind
    quality: str
    entry_ids: list[str]
    temp_dir: Path
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

    def to_response(self) -> JobStatusResponse:
        return JobStatusResponse(
            jobId=self.id,
            status=self.status,
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
        )


class JobManager:
    def __init__(self, temp_root: Path, max_active_jobs: int) -> None:
        self.temp_root = temp_root
        self.max_active_jobs = max_active_jobs
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.RLock()

    def create(self, url: str, kind: MediaKind, quality: str, entry_ids: list[str]) -> Job:
        with self._lock:
            if self.active_count() >= self.max_active_jobs:
                raise RuntimeError("Another download is already running.")

            job_id = uuid.uuid4().hex
            job = Job(
                id=job_id,
                url=url,
                kind=kind,
                quality=quality,
                entry_ids=entry_ids,
                temp_dir=self.temp_root / job_id,
            )
            self._jobs[job_id] = job
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

    def cancel(self, job_id: str) -> Optional[Job]:
        job = self.get(job_id)
        if job is None:
            return None
        job.cancel_event.set()
        self.update(job, status=JobState.cancelled, message="Cancelling")
        return job

    def remove(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.pop(job_id, None)

    def all(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())
