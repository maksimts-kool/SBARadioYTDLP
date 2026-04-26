from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from .admin import (
    ACTIVE_JOB_STATES,
    AdminBlockedDevicesResponse,
    AdminCleanupResponse,
    AdminDashboardResponse,
    AdminDeviceBlockRequest,
    AdminLoginRequest,
    AdminSessionResponse,
    AdminState,
    build_disk_response,
    remove_path_with_count,
    scan_temp_files,
)
from .config import get_settings
from .downloader import extract_preview, run_download_job
from .jobs import JobManager
from .models import JobCreateRequest, JobState, JobStatusResponse, PreviewRequest, PreviewResponse, utc_now
from .storage import ensure_directory, remove_directory
from .validation import enforce_playlist_limit, validate_quality, validate_youtube_url

settings = get_settings()
manager = JobManager(settings.temp_root, settings.max_active_jobs, settings.admin_history_limit)
admin_state = AdminState(settings.admin_state_path, settings.admin_history_limit)
started_at = utc_now()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directory(settings.temp_root)
    cleanup_task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="SBARadioYTDLP API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origin_list,
    allow_origin_regex=settings.allowed_origin_regex_pattern,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_tracking_middleware(request: Request, call_next):
    ip = client_ip(request)
    device_id = connection_device_id(request)
    admin_state.record_device(device_id, ip, request.headers.get("user-agent", ""), request.url.path)

    if admin_state.is_device_blocked(device_id):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": "Your device is blocked."})

    return await call_next(request)


def require_admin(authorization: str | None = Header(default=None)) -> None:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or not admin_state.validate_session(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin login required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.get("/api/health")
def health() -> dict[str, object]:
    return build_health_payload()


@app.get("/api/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/ready")
def readiness(response: Response) -> dict[str, object]:
    payload = build_health_payload()
    if payload["status"] != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload


@app.post("/api/preview", response_model=PreviewResponse)
def preview_media(payload: PreviewRequest) -> PreviewResponse:
    url = validate_youtube_url(payload.url)
    return extract_preview(url, settings)


@app.post("/api/jobs", response_model=JobStatusResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreateRequest,
    background_tasks: BackgroundTasks,
    x_device_id: str | None = Header(default=None),
) -> JobStatusResponse:
    if not payload.termsAccepted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Confirm that you have the right to download this media.")

    url = validate_youtube_url(payload.url)
    quality = validate_quality(payload.kind.value, payload.quality)
    entry_ids = list(dict.fromkeys(payload.entryIds))
    enforce_playlist_limit(entry_ids, settings.max_playlist_items)

    try:
        job = manager.create(
            url=url,
            kind=payload.kind,
            quality=quality,
            entry_ids=entry_ids,
            media_title=clean_media_title(payload.mediaTitle),
            device_id=clean_device_id(x_device_id),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    background_tasks.add_task(run_download_job, job, manager, settings)
    return job.to_response(settings.cleanup_after_seconds)


@app.get("/api/jobs/available", response_model=list[JobStatusResponse])
def list_available_jobs(x_device_id: str | None = Header(default=None)) -> list[JobStatusResponse]:
    device_id = clean_device_id(x_device_id)
    if device_id is None:
        return []

    jobs = []
    for job in manager.all():
        if job.device_id != device_id:
            continue
        if job.status != JobState.ready or job.output_path is None:
            continue
        output_path = Path(job.output_path)
        if output_path.exists() and output_path.is_file():
            jobs.append(job.to_response(settings.cleanup_after_seconds))
    return sorted(jobs, key=lambda item: item.updatedAt, reverse=True)


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str) -> JobStatusResponse:
    try:
        return manager.require(job_id).to_response(settings.cleanup_after_seconds)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.") from exc


@app.websocket("/api/jobs/{job_id}/events")
async def job_events(websocket: WebSocket, job_id: str) -> None:
    ip = client_ip(websocket)
    device_id = connection_device_id(websocket)
    admin_state.record_device(device_id, ip, websocket.headers.get("user-agent", ""), websocket.url.path)
    if admin_state.is_device_blocked(device_id):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    last_payload = None
    try:
        while True:
            job = manager.get(job_id)
            if job is None:
                await websocket.send_json({"error": "Job not found."})
                await websocket.close(code=1008)
                return

            payload = job.to_response(settings.cleanup_after_seconds).model_dump(mode="json")
            if payload != last_payload:
                await websocket.send_json(payload)
                last_payload = payload

            if job.status in {JobState.ready, JobState.failed, JobState.cancelled}:
                await asyncio.sleep(0.25)
                await websocket.close()
                return

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return


@app.get("/api/jobs/{job_id}/download")
def download_job(job_id: str, request: Request) -> FileResponse:
    try:
        job = manager.require(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.") from exc

    if job.status != JobState.ready or job.output_path is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Download is not ready yet.")

    path = Path(job.output_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="The temporary file is no longer available.")

    transfer_id = admin_state.start_upload(job.id, client_ip(request), path.name, path.stat().st_size)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
        background=BackgroundTask(admin_state.finish_upload, transfer_id),
    )


@app.delete("/api/jobs/{job_id}", response_model=JobStatusResponse)
def cancel_or_cleanup_job(job_id: str) -> JobStatusResponse:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    if job.status in {JobState.ready, JobState.failed, JobState.cancelled}:
        removed = manager.remove(job_id)
        if removed:
            remove_directory(removed.temp_dir)
            return removed.to_response(settings.cleanup_after_seconds)

    manager.cancel(job_id)
    return job.to_response(settings.cleanup_after_seconds)


@app.post("/api/admin/login", response_model=AdminSessionResponse)
def admin_login(payload: AdminLoginRequest) -> AdminSessionResponse:
    session = admin_state.create_session(payload.password, settings.admin_password, settings.admin_session_ttl_seconds)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect admin password.")
    return session


@app.get("/api/admin/summary", response_model=AdminDashboardResponse)
def admin_summary(_: None = Depends(require_admin)) -> AdminDashboardResponse:
    return build_admin_dashboard()


@app.post("/api/admin/blocked-devices", response_model=AdminBlockedDevicesResponse)
def block_device(payload: AdminDeviceBlockRequest, request: Request, _: None = Depends(require_admin)) -> AdminBlockedDevicesResponse:
    return admin_state.block_device(payload.deviceId.strip(), admin_ip=client_ip(request))


@app.delete("/api/admin/blocked-devices/{device_id}", response_model=AdminBlockedDevicesResponse)
def unblock_device(device_id: str, request: Request, _: None = Depends(require_admin)) -> AdminBlockedDevicesResponse:
    return admin_state.unblock_device(device_id.strip(), admin_ip=client_ip(request))


@app.post("/api/admin/temp/cleanup", response_model=AdminCleanupResponse)
def cleanup_temp_files(request: Request, _: None = Depends(require_admin)) -> AdminCleanupResponse:
    ensure_directory(settings.temp_root)
    totals = AdminCleanupResponse(removedFiles=0, removedDirectories=0, removedBytes=0)
    active_dirs = {job.temp_dir.resolve() for job in manager.all() if job.status in ACTIVE_JOB_STATES}
    state_paths = {settings.admin_state_path.resolve(), settings.admin_state_path.with_suffix(f"{settings.admin_state_path.suffix}.tmp").resolve()}

    for job in manager.all():
        if job.status in ACTIVE_JOB_STATES:
            continue
        manager.remove(job.id)
        add_cleanup_result(totals, remove_path_with_count(job.temp_dir))

    for child in settings.temp_root.iterdir():
        try:
            resolved = child.resolve()
        except OSError:
            continue
        if any(resolved == state_path or resolved in state_path.parents for state_path in state_paths) or resolved in active_dirs:
            continue
        add_cleanup_result(totals, remove_path_with_count(child))

    admin_state.record_event(
        "cleanup",
        f"Removed {totals.removedFiles} files and {totals.removedDirectories} directories",
        ip=client_ip(request),
    )
    return totals


@app.delete("/api/admin/temp/{job_id}", response_model=AdminCleanupResponse)
def delete_job_temp(job_id: str, request: Request, _: None = Depends(require_admin)) -> AdminCleanupResponse:
    if not job_id.strip() or Path(job_id).name != job_id or job_id in {".", ".."}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid temp path.")

    job = manager.get(job_id)
    if job and job.status in ACTIVE_JOB_STATES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Active job temp files cannot be deleted.")

    target = (settings.temp_root / job_id).resolve()
    root = settings.temp_root.resolve()
    if target == root or root not in target.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid temp path.")

    if job:
        manager.remove(job_id)

    result = remove_path_with_count(target)
    admin_state.record_event("cleanup", f"Deleted temp files for job {job_id}", ip=client_ip(request), job_id=job_id)
    return result


def build_admin_dashboard() -> AdminDashboardResponse:
    jobs = manager.all()
    current_jobs = sorted([job.to_response() for job in jobs], key=lambda item: item.updatedAt, reverse=True)
    job_history = manager.history()
    temp_files = scan_temp_files(settings.temp_root, jobs, job_history, settings.admin_state_path)
    available_files = [file for file in temp_files if file.isOutput and file.downloadUrl]

    return AdminDashboardResponse(
        serverTime=utc_now(),
        uptimeSeconds=round((utc_now() - started_at).total_seconds(), 2),
        activeJobs=manager.active_count(),
        maxActiveJobs=settings.max_active_jobs,
        disk=build_disk_response(settings.temp_root, settings.cleanup_after_seconds),
        currentJobs=current_jobs,
        jobHistory=job_history,
        availableFiles=available_files,
        tempFiles=temp_files,
        devices=admin_state.devices(),
        blockedDevices=admin_state.blocked_devices(),
        activeUploads=admin_state.active_uploads(),
        uploadHistory=admin_state.upload_history(),
        events=admin_state.events(),
    )


def add_cleanup_result(total: AdminCleanupResponse, item: AdminCleanupResponse) -> None:
    total.removedFiles += item.removedFiles
    total.removedDirectories += item.removedDirectories
    total.removedBytes += item.removedBytes


def client_ip(connection: Request | WebSocket) -> str:
    forwarded_for = connection.headers.get("x-forwarded-for", "")
    if forwarded_for:
        first_ip = forwarded_for.split(",", 1)[0].strip()
        if first_ip:
            return first_ip

    real_ip = connection.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip

    if connection.client and connection.client.host:
        return connection.client.host
    return "unknown"


def clean_device_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 128:
        return None
    return cleaned


def connection_device_id(connection: Request | WebSocket) -> str | None:
    header_value = connection.headers.get("x-device-id")
    if header_value:
        return clean_device_id(header_value)
    return clean_device_id(connection.query_params.get("deviceId"))


def clean_media_title(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned[:300] or None


async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(settings.cleanup_interval_seconds)
        cleanup_old_jobs()


def cleanup_old_jobs() -> None:
    now = utc_now()
    terminal = {JobState.ready, JobState.failed, JobState.cancelled}
    for job in manager.all():
        if job.status not in terminal:
            continue
        age = (now - job.updated_at).total_seconds()
        if age >= settings.cleanup_after_seconds:
            removed = manager.remove(job.id)
            if removed:
                remove_directory(removed.temp_dir)


def build_health_payload() -> dict[str, object]:
    checks = {
        "tempRoot": check_temp_root(),
        "redis": check_redis(),
    }
    is_ready = all(check["ok"] for check in checks.values())

    return {
        "status": "ok" if is_ready else "degraded",
        "uptimeSeconds": round((utc_now() - started_at).total_seconds(), 2),
        "activeJobs": manager.active_count(),
        "maxActiveJobs": settings.max_active_jobs,
        "checks": checks,
    }


def check_temp_root() -> dict[str, object]:
    probe_path = settings.temp_root / ".healthcheck"
    try:
        ensure_directory(settings.temp_root)
        probe_path.write_text("ok", encoding="utf-8")
        probe_path.unlink(missing_ok=True)
    except OSError as exc:
        return {
            "ok": False,
            "message": f"Temp root is not writable: {exc}",
        }

    return {
        "ok": True,
        "message": "Temp root is writable",
    }


def check_redis() -> dict[str, object]:
    redis_url = settings.redis_connection_url
    if redis_url is None:
        return {
            "ok": True,
            "message": "Redis check disabled",
        }

    try:
        import redis

        client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=settings.redis_healthcheck_timeout_seconds,
            socket_timeout=settings.redis_healthcheck_timeout_seconds,
        )
        try:
            client.ping()
        finally:
            client.close()
    except ImportError:
        return {
            "ok": False,
            "message": "Redis package is not installed",
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Redis is not reachable: {exc}",
        }

    return {
        "ok": True,
        "message": "Redis ping succeeded",
    }
