from __future__ import annotations

import json
import secrets
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from .models import JobState, JobStatusResponse, utc_now


ACTIVE_JOB_STATES = {JobState.queued, JobState.metadata, JobState.downloading, JobState.converting, JobState.archiving}
TERMINAL_JOB_STATES = {JobState.ready, JobState.failed, JobState.cancelled}


class AdminLoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class AdminSessionResponse(BaseModel):
    token: str
    expiresAt: datetime


class AdminDeviceBlockRequest(BaseModel):
    deviceId: str = Field(min_length=1, max_length=128)


class AdminBlockedDevicesResponse(BaseModel):
    blockedDevices: list[str]


class AdminCleanupResponse(BaseModel):
    removedFiles: int
    removedDirectories: int
    removedBytes: int


class AdminDiskResponse(BaseModel):
    tempRoot: str
    totalBytes: int
    usedBytes: int
    freeBytes: int
    tempBytes: int
    usagePercent: float
    cleanupAfterSeconds: int


class AdminFileResponse(BaseModel):
    relativePath: str
    name: str
    jobId: Optional[str] = None
    status: Optional[str] = None
    sizeBytes: int
    modifiedAt: datetime
    downloadUrl: Optional[str] = None
    isOutput: bool = False
    deletable: bool = True


class AdminDeviceResponse(BaseModel):
    deviceId: str
    lastIp: str
    firstSeen: datetime
    lastSeen: datetime
    requestCount: int
    lastPath: str
    userAgent: str
    blocked: bool


class AdminTransferResponse(BaseModel):
    transferId: str
    direction: Literal["upload"] = "upload"
    jobId: str
    ip: str
    fileName: str
    sizeBytes: int
    status: Literal["active", "completed", "failed"]
    startedAt: datetime
    completedAt: Optional[datetime] = None


class AdminEventResponse(BaseModel):
    eventId: str
    category: str
    message: str
    ip: Optional[str] = None
    jobId: Optional[str] = None
    createdAt: datetime


class AdminDashboardResponse(BaseModel):
    serverTime: datetime
    uptimeSeconds: float
    activeJobs: int
    maxActiveJobs: int
    disk: AdminDiskResponse
    currentJobs: list[JobStatusResponse]
    jobHistory: list[JobStatusResponse]
    availableFiles: list[AdminFileResponse]
    tempFiles: list[AdminFileResponse]
    devices: list[AdminDeviceResponse]
    blockedDevices: list[str]
    activeUploads: list[AdminTransferResponse]
    uploadHistory: list[AdminTransferResponse]
    events: list[AdminEventResponse]


@dataclass
class DeviceRecord:
    device_id: str
    last_ip: str
    first_seen: datetime
    last_seen: datetime
    request_count: int = 0
    last_path: str = ""
    user_agent: str = ""

    def to_response(self, blocked: bool) -> AdminDeviceResponse:
        return AdminDeviceResponse(
            deviceId=self.device_id,
            lastIp=self.last_ip,
            firstSeen=self.first_seen,
            lastSeen=self.last_seen,
            requestCount=self.request_count,
            lastPath=self.last_path,
            userAgent=self.user_agent,
            blocked=blocked,
        )


@dataclass
class TransferRecord:
    transfer_id: str
    job_id: str
    ip: str
    file_name: str
    size_bytes: int
    status: Literal["active", "completed", "failed"]
    started_at: datetime
    completed_at: Optional[datetime] = None

    def to_response(self) -> AdminTransferResponse:
        return AdminTransferResponse(
            transferId=self.transfer_id,
            jobId=self.job_id,
            ip=self.ip,
            fileName=self.file_name,
            sizeBytes=self.size_bytes,
            status=self.status,
            startedAt=self.started_at,
            completedAt=self.completed_at,
        )


@dataclass
class EventRecord:
    event_id: str
    category: str
    message: str
    created_at: datetime
    ip: Optional[str] = None
    job_id: Optional[str] = None

    def to_response(self) -> AdminEventResponse:
        return AdminEventResponse(
            eventId=self.event_id,
            category=self.category,
            message=self.message,
            ip=self.ip,
            jobId=self.job_id,
            createdAt=self.created_at,
        )


class AdminState:
    def __init__(self, state_path: Path, max_events: int = 200) -> None:
        self.state_path = state_path
        self.max_events = max_events
        self._lock = threading.RLock()
        self._devices: dict[str, DeviceRecord] = {}
        self._blocked_devices: set[str] = set()
        self._sessions: dict[str, datetime] = {}
        self._active_transfers: dict[str, TransferRecord] = {}
        self._transfer_history: list[TransferRecord] = []
        self._events: list[EventRecord] = []
        self._load()

    def create_session(self, password: str, expected_password: str, ttl_seconds: int) -> Optional[AdminSessionResponse]:
        if not secrets.compare_digest(password, expected_password):
            return None

        expires_at = utc_now() + timedelta(seconds=ttl_seconds)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = expires_at
        return AdminSessionResponse(token=token, expiresAt=expires_at)

    def validate_session(self, token: str) -> bool:
        now = utc_now()
        with self._lock:
            expired_tokens = [session_token for session_token, expires_at in self._sessions.items() if expires_at <= now]
            for session_token in expired_tokens:
                self._sessions.pop(session_token, None)

            expires_at = self._sessions.get(token)
            return bool(expires_at and expires_at > now)

    def record_device(self, device_id: str | None, ip: str, user_agent: str, path: str) -> None:
        if not device_id:
            return

        now = utc_now()
        should_save = False
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                device = DeviceRecord(device_id=device_id, last_ip=ip, first_seen=now, last_seen=now)
                self._devices[device_id] = device
                should_save = True

            device.last_ip = ip
            device.last_seen = now
            device.request_count += 1
            device.last_path = path[:512]
            device.user_agent = user_agent[:512]
            should_save = should_save or device.request_count % 10 == 0

            if should_save:
                self._save_locked()

    def is_device_blocked(self, device_id: str | None) -> bool:
        if not device_id:
            return False
        with self._lock:
            return device_id in self._blocked_devices

    def block_device(self, device_id: str, admin_ip: str | None = None) -> AdminBlockedDevicesResponse:
        with self._lock:
            self._blocked_devices.add(device_id)
            self._add_event_locked("security", f"Blocked device {device_id}", ip=admin_ip)
            self._save_locked()
            return AdminBlockedDevicesResponse(blockedDevices=sorted(self._blocked_devices))

    def unblock_device(self, device_id: str, admin_ip: str | None = None) -> AdminBlockedDevicesResponse:
        with self._lock:
            self._blocked_devices.discard(device_id)
            self._add_event_locked("security", f"Unblocked device {device_id}", ip=admin_ip)
            self._save_locked()
            return AdminBlockedDevicesResponse(blockedDevices=sorted(self._blocked_devices))

    def blocked_devices(self) -> list[str]:
        with self._lock:
            return sorted(self._blocked_devices)

    def devices(self) -> list[AdminDeviceResponse]:
        with self._lock:
            return sorted(
                [device.to_response(device.device_id in self._blocked_devices) for device in self._devices.values()],
                key=lambda device: device.lastSeen,
                reverse=True,
            )

    def start_upload(self, job_id: str, ip: str, file_name: str, size_bytes: int) -> str:
        transfer = TransferRecord(
            transfer_id=uuid.uuid4().hex,
            job_id=job_id,
            ip=ip,
            file_name=file_name,
            size_bytes=size_bytes,
            status="active",
            started_at=utc_now(),
        )
        with self._lock:
            self._active_transfers[transfer.transfer_id] = transfer
            self._add_event_locked("upload", f"Started serving {file_name}", ip=ip, job_id=job_id)
            self._save_locked()
        return transfer.transfer_id

    def finish_upload(self, transfer_id: str) -> None:
        self._complete_upload(transfer_id, "completed")

    def fail_upload(self, transfer_id: str) -> None:
        self._complete_upload(transfer_id, "failed")

    def active_uploads(self) -> list[AdminTransferResponse]:
        with self._lock:
            return sorted(
                [transfer.to_response() for transfer in self._active_transfers.values()],
                key=lambda transfer: transfer.startedAt,
                reverse=True,
            )

    def upload_history(self) -> list[AdminTransferResponse]:
        with self._lock:
            return [transfer.to_response() for transfer in reversed(self._transfer_history)]

    def events(self) -> list[AdminEventResponse]:
        with self._lock:
            return [event.to_response() for event in reversed(self._events)]

    def record_event(self, category: str, message: str, ip: str | None = None, job_id: str | None = None) -> None:
        with self._lock:
            self._add_event_locked(category, message, ip=ip, job_id=job_id)
            self._save_locked()

    def _complete_upload(self, transfer_id: str, status_value: Literal["completed", "failed"]) -> None:
        with self._lock:
            transfer = self._active_transfers.pop(transfer_id, None)
            if transfer is None:
                return

            transfer.status = status_value
            transfer.completed_at = utc_now()
            self._transfer_history.append(transfer)
            self._transfer_history = self._transfer_history[-self.max_events :]
            self._add_event_locked("upload", f"{status_value.title()} serving {transfer.file_name}", ip=transfer.ip, job_id=transfer.job_id)
            self._save_locked()

    def _add_event_locked(self, category: str, message: str, ip: str | None = None, job_id: str | None = None) -> None:
        self._events.append(
            EventRecord(
                event_id=uuid.uuid4().hex,
                category=category,
                message=message,
                ip=ip,
                job_id=job_id,
                created_at=utc_now(),
            )
        )
        self._events = self._events[-self.max_events :]

    def _load(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        with self._lock:
            self._blocked_devices = set(payload.get("blockedDevices") or [])
            self._devices = {}
            for raw in payload.get("devices") or []:
                try:
                    device = DeviceRecord(
                        device_id=str(raw["deviceId"]),
                        last_ip=str(raw.get("lastIp") or ""),
                        first_seen=parse_datetime(raw["firstSeen"]),
                        last_seen=parse_datetime(raw["lastSeen"]),
                        request_count=int(raw.get("requestCount") or 0),
                        last_path=str(raw.get("lastPath") or ""),
                        user_agent=str(raw.get("userAgent") or ""),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                self._devices[device.device_id] = device

            self._transfer_history = []
            for raw in payload.get("uploadHistory") or []:
                try:
                    self._transfer_history.append(
                        TransferRecord(
                            transfer_id=str(raw["transferId"]),
                            job_id=str(raw["jobId"]),
                            ip=str(raw.get("ip") or ""),
                            file_name=str(raw.get("fileName") or ""),
                            size_bytes=int(raw.get("sizeBytes") or 0),
                            status=raw.get("status") if raw.get("status") in {"completed", "failed"} else "completed",
                            started_at=parse_datetime(raw["startedAt"]),
                            completed_at=parse_optional_datetime(raw.get("completedAt")),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            self._transfer_history = self._transfer_history[-self.max_events :]

            self._events = []
            for raw in payload.get("events") or []:
                try:
                    self._events.append(
                        EventRecord(
                            event_id=str(raw["eventId"]),
                            category=str(raw.get("category") or "system"),
                            message=str(raw.get("message") or ""),
                            ip=optional_string(raw.get("ip")),
                            job_id=optional_string(raw.get("jobId")),
                            created_at=parse_datetime(raw["createdAt"]),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            self._events = self._events[-self.max_events :]

    def _save_locked(self) -> None:
        payload = {
            "blockedDevices": sorted(self._blocked_devices),
            "devices": [
                {
                    "deviceId": device.device_id,
                    "lastIp": device.last_ip,
                    "firstSeen": device.first_seen.isoformat(),
                    "lastSeen": device.last_seen.isoformat(),
                    "requestCount": device.request_count,
                    "lastPath": device.last_path,
                    "userAgent": device.user_agent,
                }
                for device in sorted(self._devices.values(), key=lambda item: item.last_seen, reverse=True)
            ],
            "uploadHistory": [transfer.to_response().model_dump(mode="json") for transfer in self._transfer_history],
            "events": [event.to_response().model_dump(mode="json") for event in self._events],
        }

        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
            temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temp_path.replace(self.state_path)
        except OSError:
            return


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=utc_now().tzinfo)


def parse_optional_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    return parse_datetime(str(value))


def optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text or None


def build_disk_response(temp_root: Path, cleanup_after_seconds: int) -> AdminDiskResponse:
    temp_root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(temp_root)
    used = usage.total - usage.free
    usage_percent = round((used / usage.total) * 100, 2) if usage.total else 0
    return AdminDiskResponse(
        tempRoot=str(temp_root),
        totalBytes=usage.total,
        usedBytes=used,
        freeBytes=usage.free,
        tempBytes=directory_size(temp_root),
        usagePercent=usage_percent,
        cleanupAfterSeconds=cleanup_after_seconds,
    )


def scan_temp_files(temp_root: Path, jobs: list[Any], job_history: list[JobStatusResponse], state_path: Path) -> list[AdminFileResponse]:
    if not temp_root.exists():
        return []

    jobs_by_id = {job.id: job for job in jobs}
    history_by_id = {snapshot.jobId: snapshot for snapshot in job_history}
    state_paths = {state_path.resolve(), state_path.with_suffix(f"{state_path.suffix}.tmp").resolve()}
    files: list[AdminFileResponse] = []

    for path in temp_root.rglob("*"):
        try:
            resolved = path.resolve()
        except OSError:
            continue

        if resolved in state_paths or not path.is_file():
            continue

        try:
            relative = path.relative_to(temp_root)
            stat = path.stat()
        except OSError:
            continue

        parts = relative.parts
        job_id = parts[0] if parts else None
        job = jobs_by_id.get(job_id or "")
        snapshot = history_by_id.get(job_id or "")
        status_value = job.status.value if job else snapshot.status.value if snapshot else None
        output_path = job.output_path if job else None
        is_output = bool(output_path and output_path.resolve() == resolved)
        download_url = f"/api/jobs/{job_id}/download" if is_output and status_value == JobState.ready.value else None
        deletable = not (job and job.status in ACTIVE_JOB_STATES)

        files.append(
            AdminFileResponse(
                relativePath=relative.as_posix(),
                name=path.name,
                jobId=job_id,
                status=status_value,
                sizeBytes=stat.st_size,
                modifiedAt=datetime.fromtimestamp(stat.st_mtime, tz=utc_now().tzinfo),
                downloadUrl=download_url,
                isOutput=is_output,
                deletable=deletable,
            )
        )

    return sorted(files, key=lambda item: item.modifiedAt, reverse=True)


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0

    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def remove_path_with_count(path: Path) -> AdminCleanupResponse:
    removed_files = 0
    removed_directories = 0
    removed_bytes = 0

    if not path.exists():
        return AdminCleanupResponse(removedFiles=0, removedDirectories=0, removedBytes=0)

    if path.is_file():
        try:
            removed_bytes = path.stat().st_size
            path.unlink()
            removed_files = 1
        except OSError:
            pass
        return AdminCleanupResponse(removedFiles=removed_files, removedDirectories=0, removedBytes=removed_bytes)

    for child in path.rglob("*"):
        try:
            if child.is_file():
                removed_files += 1
                removed_bytes += child.stat().st_size
            elif child.is_dir():
                removed_directories += 1
        except OSError:
            continue

    try:
        shutil.rmtree(path, ignore_errors=True)
        removed_directories += 1
    except OSError:
        pass

    return AdminCleanupResponse(removedFiles=removed_files, removedDirectories=removed_directories, removedBytes=removed_bytes)
