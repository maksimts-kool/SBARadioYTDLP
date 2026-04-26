from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Optional

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
    cancel_check: Optional[Callable[[str], bool]] = field(default=None, repr=False, compare=False)
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

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "url": self.url,
            "kind": self.kind.value,
            "quality": self.quality,
            "entryIds": self.entry_ids,
            "tempDir": str(self.temp_dir),
            "mediaTitle": self.media_title,
            "deviceId": self.device_id,
            "status": self.status.value,
            "progress": self.progress,
            "currentItem": self.current_item,
            "totalItems": self.total_items,
            "completedItems": self.completed_items,
            "message": self.message,
            "error": self.error,
            "outputPath": str(self.output_path) if self.output_path else None,
            "isArchive": self.is_archive,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> Job:
        output_path = payload.get("outputPath")
        job = cls(
            id=str(payload["id"]),
            url=str(payload["url"]),
            kind=MediaKind(str(payload["kind"])),
            quality=str(payload["quality"]),
            entry_ids=[str(item) for item in payload.get("entryIds") or []],
            temp_dir=Path(str(payload["tempDir"])),
            media_title=optional_string(payload.get("mediaTitle")),
            device_id=optional_string(payload.get("deviceId")),
            status=JobState(str(payload.get("status") or JobState.queued.value)),
            progress=float(payload.get("progress") or 0),
            current_item=optional_string(payload.get("currentItem")),
            total_items=int(payload.get("totalItems") or 0),
            completed_items=int(payload.get("completedItems") or 0),
            message=optional_string(payload.get("message")),
            error=optional_string(payload.get("error")),
            output_path=Path(str(output_path)) if output_path else None,
            is_archive=bool(payload.get("isArchive")),
            created_at=parse_datetime(str(payload["createdAt"])),
            updated_at=parse_datetime(str(payload["updatedAt"])),
        )
        if job.status == JobState.cancelled:
            job.cancel_event.set()
        return job


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
        enforce_capacity: bool = True,
        enqueue: bool = False,
    ) -> Job:
        job_id = uuid.uuid4().hex
        with self._lock:
            if enforce_capacity and self.active_count() >= self.max_active_jobs:
                raise RuntimeError("Another download is already running.")
            try:
                if enforce_capacity and self.redis_store and not self.redis_store.reserve_active_slot(job_id, self.max_active_jobs):
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
            self._attach_cancel_checker(job)
            self._jobs[job_id] = job
            self._remember(job)
            if self.redis_store and enqueue:
                self.redis_store.enqueue_job(job.id)
            return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return job
            if not self.redis_store:
                return None
            payload = self.redis_store.load_job_payload(job_id)
            if payload is None:
                return None
            job = Job.from_payload(payload)
            self._attach_cancel_checker(job)
            self._jobs[job.id] = job
            return job

    def require(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def active_count(self) -> int:
        if self.redis_store:
            try:
                return self.redis_store.active_count()
            except Exception:
                return 0
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
            jobs_by_id = dict(self._jobs)
            if self.redis_store:
                try:
                    for payload in self.redis_store.load_history_payloads(self.history_limit):
                        job = Job.from_payload(payload)
                        self._attach_cancel_checker(job)
                        jobs_by_id[job.id] = job
                except Exception:
                    pass
            return list(jobs_by_id.values())

    def history(self) -> list[JobStatusResponse]:
        with self._lock:
            if self.redis_store:
                try:
                    for snapshot in reversed(self.redis_store.load_history(self.history_limit)):
                        if snapshot.jobId not in self._history:
                            self._history_order.append(snapshot.jobId)
                        self._history[snapshot.jobId] = snapshot
                except Exception:
                    pass
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
                self.redis_store.save_job_payload(job.to_payload())
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

    def _attach_cancel_checker(self, job: Job) -> None:
        if self.redis_store:
            job.cancel_check = self.redis_store.is_cancel_requested


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=utc_now().tzinfo)


def optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
