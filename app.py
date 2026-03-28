import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from threading import Lock, Thread
from typing import Any

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis import Redis
from requests.adapters import HTTPAdapter
from rq import Queue, get_current_job
from rq.job import Job
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from urllib3.util.retry import Retry

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    azuracast_station_id: str = Field(default="2", alias="AZURACAST_STATION_ID")
    azuracast_api_key: str = Field(default="", alias="AZURACAST_API_KEY")
    youtube_playlist_url: str = Field(
        default="https://music.youtube.com/playlist?list=PLq0zpvHX8lQrhRG4qYCPC0ywFo_UhU_F8",
        alias="YOUTUBE_PLAYLIST_URL",
    )
    download_dir: str = Field(default="Downloaded", alias="DOWNLOAD_DIR")
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=5000, alias="APP_PORT")
    flask_debug: bool = Field(default=False, alias="FLASK_DEBUG")
    use_waitress: bool = Field(default=True, alias="USE_WAITRESS")
    waitress_threads: int = Field(default=4, alias="WAITRESS_THREADS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    azuracast_base_url: str = Field(
        default="https://radio.maksimtsikvasvili24.thkit.ee",
        alias="AZURACAST_BASE_URL",
    )
    requests_timeout: int = Field(default=30, alias="REQUESTS_TIMEOUT")
    requests_retries: int = Field(default=3, alias="REQUESTS_RETRIES")
    requests_backoff_seconds: float = Field(default=1.0, alias="REQUESTS_BACKOFF_SECONDS")
    job_backend: str = Field(default="memory", alias="JOB_BACKEND")
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", alias="REDIS_URL")

    @field_validator("job_backend")
    @classmethod
    def validate_job_backend(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized not in {"memory", "rq"}:
            raise ValueError("JOB_BACKEND must be either 'memory' or 'rq'.")
        return normalized

    @field_validator("download_dir")
    @classmethod
    def validate_download_dir(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("DOWNLOAD_DIR cannot be empty.")
        return cleaned


settings = AppSettings()

logger.remove()
logger.add(
    os.sys.stderr,
    level=settings.log_level.upper(),
    enqueue=True,
    backtrace=settings.flask_debug,
    diagnose=settings.flask_debug,
)

app = Flask(__name__)


DEFAULT_CONFIG = {
    "STATION_ID": settings.azuracast_station_id,
    "API_KEY": settings.azuracast_api_key,
    "PLAYLIST_URL": settings.youtube_playlist_url,
    "DOWNLOAD_DIR": settings.download_dir,
}


class AnalyzeRequest(BaseModel):
    station_id: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    playlist_url: str = Field(min_length=1)
    download_dir: str = Field(default=settings.download_dir, min_length=1)

    @field_validator("station_id", "api_key", "playlist_url", "download_dir")
    @classmethod
    def strip_values(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("Field cannot be empty.")
        return cleaned


class TrackPayload(BaseModel):
    id: str | None = None
    url: str = Field(min_length=1)
    clean_artist: str = Field(min_length=1)
    title: str = Field(min_length=1)

    @field_validator("url", "clean_artist", "title")
    @classmethod
    def strip_track_fields(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("Track field cannot be empty.")
        return cleaned


class DownloadRequest(BaseModel):
    tracks: list[TrackPayload] = Field(min_length=1)
    download_dir: str = Field(default=settings.download_dir, min_length=1)

    @field_validator("download_dir")
    @classmethod
    def strip_download_dir(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("download_dir cannot be empty.")
        return cleaned


def build_job_state(job_id: str, tracks: list[dict[str, Any]], download_dir: str) -> dict[str, Any]:
    return {
        "id": job_id,
        "status": "queued",
        "progress": 0,
        "total": len(tracks),
        "current_track": "Queued",
        "download_speed": "--",
        "download_dir": download_dir,
        "logs": ["Queued download job."],
        "completed": 0,
        "result": None,
        "error": None,
    }


def normalize(value: str) -> str:
    return (value or "").strip().lower()


def clean_for_ffmpeg(text: str) -> str:
    if not text:
        return ""
    return text.replace('"', "'").replace("\\", "")


def clean_junk(text: str) -> str:
    if not text:
        return ""
    junk_keywords = (
        "official|video|audio|lyric|visualizer|hq|hd|clean|music|version|4k|1080p|"
        "clip|performance|live|remastered|extended|radio edit|explicit|visual"
    )
    text = re.sub(r"(?i)\s*[\[\(].*?(" + junk_keywords + r").*?[\]\)]", "", text)
    text = re.sub(r"#\S+", "", text)
    text = re.sub(r"(?i)\s+(official|video|audio|lyric|lyrics|music|clean)+$", "", text)
    return text.strip()


def smart_parse(raw_title: str, raw_uploader: str):
    clean_full_title = clean_junk(raw_title)

    is_official = False
    clean_uploader = "Unknown Artist"
    if raw_uploader and raw_uploader != "NA":
        if re.search(r"(?i)\s*-\s*Topic$|VEVO$", raw_uploader):
            is_official = True
        clean_uploader = re.sub(r"(?i)\s*-\s*Topic$", "", raw_uploader)
        clean_uploader = re.sub(r"(?i)\s*VEVO$", "", clean_uploader).strip()

    separator_pattern = r"\s+[-–—]\s+"
    final_artist = ""
    final_title = ""

    if re.search(separator_pattern, clean_full_title):
        parts = re.split(separator_pattern, clean_full_title)
        if normalize(parts[0]) == normalize(clean_uploader):
            final_artist = parts[0]
            final_title = " - ".join(parts[1:])
        elif is_official:
            final_artist = clean_uploader
            final_title = clean_full_title
        elif len(parts) >= 2:
            final_artist = parts[0]
            final_title = " - ".join(parts[1:])
    else:
        final_title = clean_full_title
        final_artist = clean_uploader

    if not final_title:
        final_title = raw_title or "Unknown Title"
    if not final_artist or final_artist == "NA":
        final_artist = clean_uploader if clean_uploader else "Unknown Artist"

    return final_artist, final_title


def create_retry_session() -> requests.Session:
    session = requests.Session()
    retry_config = Retry(
        total=settings.requests_retries,
        connect=settings.requests_retries,
        read=settings.requests_retries,
        backoff_factor=settings.requests_backoff_seconds,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_config)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


HTTP_SESSION = create_retry_session()


@retry(
    retry=retry_if_exception_type(requests.RequestException),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
def fetch_station_files(station_id: str, api_key: str) -> list[dict[str, Any]]:
    azuracast_api = f"{settings.azuracast_base_url.rstrip('/')}/api/station/{station_id}/files"
    logger.info("Requesting AzuraCast files for station {}", station_id)
    response = HTTP_SESSION.get(
        azuracast_api,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=settings.requests_timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise requests.RequestException("Unexpected AzuraCast response format.")
    return payload


class InMemoryJobStore:
    def __init__(self):
        self.lock = Lock()
        self.jobs: dict[str, dict[str, Any]] = {}

    def create(self, tracks: list[dict[str, Any]], download_dir: str) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job_data = build_job_state(job_id, tracks, download_dir)
        with self.lock:
            self.jobs[job_id] = job_data
        return job_data

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job_data = self.jobs.get(job_id)
            return dict(job_data) if job_data else None

    def update(self, job_id: str, **changes: Any) -> None:
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(changes)

    def append_log(self, job_id: str, message: str) -> None:
        with self.lock:
            if job_id in self.jobs:
                logs = self.jobs[job_id].setdefault("logs", [])
                logs.append(message)
                self.jobs[job_id]["logs"] = logs[-200:]


job_store = InMemoryJobStore()


def persist_job_update(job_id: str, **changes: Any) -> None:
    current_job = get_current_job()
    if current_job and current_job.id == job_id:
        current_job.meta.update(changes)
        current_job.save_meta()
        return
    job_store.update(job_id, **changes)


def persist_job_log(job_id: str, message: str) -> None:
    current_job = get_current_job()
    if current_job and current_job.id == job_id:
        logs = current_job.meta.get("logs", [])
        logs.append(message)
        current_job.meta["logs"] = logs[-200:]
        current_job.save_meta()
        return
    job_store.append_log(job_id, message)


def get_download_directory(download_dir: str) -> Path:
    target = (BASE_DIR / download_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def build_download_command(track: dict[str, Any]) -> list[str]:
    artist = track.get("clean_artist", "Unknown Artist")
    title = track.get("title", "Unknown Title")
    safe_artist = clean_for_ffmpeg(artist)
    safe_title = clean_for_ffmpeg(title)
    return [
        "yt-dlp",
        "--newline",
        "-f",
        "bestaudio/best",
        "--extractor-args",
        "youtube:player_client=android",
        "-x",
        "--audio-format",
        "mp3",
        "--embed-metadata",
        "--embed-thumbnail",
        "--convert-thumbnails",
        "jpg",
        "--postprocessor-args",
        f"ffmpeg:-metadata artist=\"{safe_artist}\" -metadata title=\"{safe_title}\"",
        "-o",
        f"{safe_artist} - {safe_title}.%(ext)s",
        track["url"],
    ]


def parse_progress_line(line: str) -> tuple[str | None, str | None]:
    match = re.search(r"(\d+\.\d+)%\s+of\s+.*?\s+at\s+(.*?)\s+ETA\s+(.*)", line)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def run_download_job(job_id: str, tracks: list[dict[str, Any]], download_dir: str) -> dict[str, Any]:
    logger.info("Starting download job {} with {} tracks", job_id, len(tracks))
    persist_job_update(job_id, status="running")
    abs_download_dir = get_download_directory(download_dir)
    total = len(tracks)
    completed = 0

    for track in tracks:
        artist = track.get("clean_artist", "Unknown Artist")
        title = track.get("title", "Unknown Title")
        current_label = f"{artist} - {title}"
        persist_job_update(job_id, current_track=current_label)
        persist_job_log(job_id, f"Processing: {current_label}")
        logger.info("Processing track {} for job {}", current_label, job_id)

        try:
            proc = subprocess.Popen(
                build_download_command(track),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=abs_download_dir,
            )

            if proc.stdout is not None:
                for raw_line in proc.stdout:
                    line = raw_line.strip()
                    if not line:
                        continue
                    percent, speed = parse_progress_line(line)
                    if percent is not None:
                        persist_job_update(job_id, progress=float(percent), download_speed=speed or "--")
                    persist_job_log(job_id, line)

            proc.wait()
            if proc.returncode != 0:
                message = f"ERROR: Failed to download {current_label}"
                logger.error(message)
                persist_job_log(job_id, message)
                persist_job_update(job_id, status="failed", error=message)
                return {"status": "failed", "error": message}
        except Exception as exc:
            message = f"ERROR: Failed to start download for {current_label}: {exc}"
            logger.exception(message)
            persist_job_log(job_id, message)
            persist_job_update(job_id, status="failed", error=message)
            return {"status": "failed", "error": message}

        completed += 1
        persist_job_update(job_id, completed=completed, progress=0, download_speed="--")
        persist_job_log(job_id, f"SUCCESS: {current_label}")

    result = {"status": "finished", "completed": total}
    persist_job_update(job_id, status="finished", result=result, current_track="Completed", progress=100)
    logger.info("Finished download job {}", job_id)
    return result


def enqueue_download_job(tracks: list[dict[str, Any]], download_dir: str) -> dict[str, Any]:
    if settings.job_backend == "rq":
        redis_connection = Redis.from_url(settings.redis_url)
        queue = Queue(connection=redis_connection)
        job_id = uuid.uuid4().hex
        job_data = build_job_state(job_id, tracks, download_dir)
        rq_job = queue.enqueue(run_download_job, job_id, tracks, download_dir, job_id=job_id)
        rq_job.meta.update(job_data)
        rq_job.save_meta()
        logger.info("Queued RQ job {} for download job {}", rq_job.id, job_id)
        return job_data

    job_data = job_store.create(tracks, download_dir)
    thread = Thread(target=run_download_job, args=(job_data["id"], tracks, download_dir), daemon=True)
    thread.start()
    job_store.update(job_data["id"], backend="memory")
    logger.info("Started in-memory background job {}", job_data["id"])
    return job_store.get(job_data["id"]) or job_data


def get_rq_job_status_payload(job_id: str) -> dict[str, Any] | None:
    try:
        redis_connection = Redis.from_url(settings.redis_url)
        rq_job = Job.fetch(job_id, connection=redis_connection)
    except Exception:
        return None

    rq_status = rq_job.get_status(refresh=True)
    status_map = {
        "queued": "queued",
        "started": "running",
        "finished": "finished",
        "failed": "failed",
        "deferred": "queued",
        "scheduled": "queued",
    }
    status = status_map.get(rq_status, rq_status)
    meta = rq_job.meta or {}
    return {
        "job_id": job_id,
        "status": status,
        "total": meta.get("total", 0),
        "completed": meta.get("completed", 0),
        "current_track": meta.get("current_track", "Queued"),
        "progress": meta.get("progress", 0),
        "download_speed": meta.get("download_speed", "--"),
        "logs": meta.get("logs", [])[-20:],
        "error": meta.get("error") or (str(rq_job.exc_info) if rq_job.is_failed else None),
    }


def get_job_status_payload(job_id: str) -> dict[str, Any] | None:
    if settings.job_backend == "rq":
        return get_rq_job_status_payload(job_id)

    job_data = job_store.get(job_id)
    if not job_data:
        return None

    return {
        "job_id": job_data["id"],
        "status": job_data.get("status", "queued"),
        "total": job_data.get("total", 0),
        "completed": job_data.get("completed", 0),
        "current_track": job_data.get("current_track", "Queued"),
        "progress": job_data.get("progress", 0),
        "download_speed": job_data.get("download_speed", "--"),
        "logs": job_data.get("logs", [])[-20:],
        "error": job_data.get("error"),
    }


def get_runtime_options() -> dict[str, Any]:
    return {
        "host": settings.app_host,
        "port": settings.app_port,
        "debug": settings.flask_debug,
        "use_waitress": settings.use_waitress,
        "threads": settings.waitress_threads,
    }


@app.errorhandler(ValidationError)
def handle_validation_error(error: ValidationError):
    logger.warning("Validation error: {}", error.errors())
    return jsonify({"error": "Validation failed", "details": error.errors()}), 400


@app.route("/")
def index():
    return render_template("index.html", config=DEFAULT_CONFIG)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "job_backend": settings.job_backend})


@app.route("/analyze", methods=["POST"])
def analyze():
    payload = AnalyzeRequest.model_validate(request.get_json(silent=True) or {})

    try:
        existing_files = fetch_station_files(payload.station_id, payload.api_key)
    except requests.RequestException as exc:
        logger.warning("AzuraCast lookup failed: {}", exc)
        existing_files = []

    existing_songs = [
        {
            "artist": normalize(file_entry.get("artist")),
            "title": normalize(file_entry.get("title")),
            "clean_title": normalize(clean_junk(file_entry.get("title"))),
            "orig_artist": file_entry.get("artist"),
        }
        for file_entry in existing_files
    ]

    abs_download_dir = BASE_DIR / payload.download_dir
    local_filenames_normalized = set()
    if abs_download_dir.exists():
        for filename in os.listdir(abs_download_dir):
            file_path = abs_download_dir / filename
            if file_path.is_file():
                local_filenames_normalized.add(normalize(file_path.stem))

    cmd = ["yt-dlp", "--flat-playlist", "--dump-single-json", payload.playlist_url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        playlist_json = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        logger.exception("Failed to fetch playlist metadata")
        return jsonify({"error": f"Failed to fetch playlist: {exc}"}), 500

    entries = playlist_json.get("entries", [])
    results = []

    for track in entries:
        raw_artist = track.get("uploader")
        raw_title = track.get("title")
        final_artist, final_title = smart_parse(raw_title, raw_artist)

        norm_title = normalize(final_title)
        norm_artist = normalize(final_artist)
        predicted_filename = normalize(f"{clean_for_ffmpeg(final_artist)} - {clean_for_ffmpeg(final_title)}")

        status = "ok"
        message = ""
        should_check = True

        if predicted_filename in local_filenames_normalized:
            status = "file_exists"
            message = "File already on disk."
            should_check = False
        elif any(song["clean_title"] == norm_title and song["artist"] == norm_artist for song in existing_songs):
            status = "skip"
            message = "Exact match on Station."
            should_check = False

        if should_check:
            title_matches = [song for song in existing_songs if song["clean_title"] == norm_title]
            if title_matches:
                status = "warning"
                match_str = ", ".join({str(song["orig_artist"]) for song in title_matches})
                message = f"Title exists (Artist: {match_str}). "

        results.append(
            {
                "id": track.get("id"),
                "url": track.get("url"),
                "original_artist": raw_artist,
                "clean_artist": final_artist,
                "title": final_title,
                "status": status,
                "message": message,
                "checked": should_check,
            }
        )

    logger.info("Analyze completed with {} track results", len(results))
    return jsonify({"tracks": results})


@app.route("/download", methods=["POST"])
def download():
    payload = DownloadRequest.model_validate(request.get_json(silent=True) or {})
    job_data = enqueue_download_job([track.model_dump() for track in payload.tracks], payload.download_dir)
    return jsonify(
        {
            "job_id": job_data["id"],
            "status": job_data["status"],
            "total": job_data["total"],
        }
    ), 202


@app.route("/download/<job_id>", methods=["GET"])
def download_status(job_id: str):
    payload = get_job_status_payload(job_id)
    if payload is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(payload)


if __name__ == "__main__":
    runtime_options = get_runtime_options()

    if runtime_options["use_waitress"] and not runtime_options["debug"]:
        from waitress import serve

        serve(
            app,
            host=runtime_options["host"],
            port=runtime_options["port"],
            threads=runtime_options["threads"],
        )
    else:
        app.run(
            debug=runtime_options["debug"],
            host=runtime_options["host"],
            port=runtime_options["port"],
        )
