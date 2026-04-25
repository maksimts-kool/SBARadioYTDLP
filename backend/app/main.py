from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import get_settings
from .downloader import extract_preview, run_download_job
from .jobs import JobManager
from .models import JobCreateRequest, JobState, JobStatusResponse, PreviewRequest, PreviewResponse, utc_now
from .storage import ensure_directory, remove_directory
from .validation import enforce_playlist_limit, validate_quality, validate_youtube_url

settings = get_settings()
manager = JobManager(settings.temp_root, settings.max_active_jobs)


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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/preview", response_model=PreviewResponse)
def preview_media(payload: PreviewRequest) -> PreviewResponse:
    url = validate_youtube_url(payload.url)
    return extract_preview(url, settings)


@app.post("/api/jobs", response_model=JobStatusResponse, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreateRequest, background_tasks: BackgroundTasks) -> JobStatusResponse:
    if not payload.termsAccepted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Confirm that you have the right to download this media.")

    url = validate_youtube_url(payload.url)
    quality = validate_quality(payload.kind.value, payload.quality)
    entry_ids = list(dict.fromkeys(payload.entryIds))
    enforce_playlist_limit(entry_ids, settings.max_playlist_items)

    try:
        job = manager.create(url=url, kind=payload.kind, quality=quality, entry_ids=entry_ids)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc

    background_tasks.add_task(run_download_job, job, manager, settings)
    return job.to_response()


@app.get("/api/jobs/available", response_model=list[JobStatusResponse])
def list_available_jobs() -> list[JobStatusResponse]:
    jobs = []
    for job in manager.all():
        if job.status != JobState.ready or job.output_path is None:
            continue
        output_path = Path(job.output_path)
        if output_path.exists() and output_path.is_file():
            jobs.append(job.to_response())
    return sorted(jobs, key=lambda item: item.updatedAt, reverse=True)


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str) -> JobStatusResponse:
    try:
        return manager.require(job_id).to_response()
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.") from exc


@app.websocket("/api/jobs/{job_id}/events")
async def job_events(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    last_payload = None
    try:
        while True:
            job = manager.get(job_id)
            if job is None:
                await websocket.send_json({"error": "Job not found."})
                await websocket.close(code=1008)
                return

            payload = job.to_response().model_dump(mode="json")
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
def download_job(job_id: str) -> FileResponse:
    try:
        job = manager.require(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.") from exc

    if job.status != JobState.ready or job.output_path is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Download is not ready yet.")

    path = Path(job.output_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="The temporary file is no longer available.")

    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.delete("/api/jobs/{job_id}", response_model=JobStatusResponse)
def cancel_or_cleanup_job(job_id: str) -> JobStatusResponse:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    if job.status in {JobState.ready, JobState.failed, JobState.cancelled}:
        removed = manager.remove(job_id)
        if removed:
            remove_directory(removed.temp_dir)
            return removed.to_response()

    manager.cancel(job_id)
    return job.to_response()


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
