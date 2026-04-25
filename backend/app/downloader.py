from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, urlparse

import yt_dlp
from fastapi import HTTPException, status

from .config import Settings
from .jobs import Job, JobManager
from .models import JobState, PreviewEntry, PreviewResponse
from .storage import ensure_directory, safe_filename, zip_files
from .validation import enforce_duration_limit, is_youtube_video_id


class DownloadCancelled(Exception):
    pass


def extract_preview(url: str, settings: Settings) -> PreviewResponse:
    try:
        opts = metadata_options(settings)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except (ValueError, yt_dlp.utils.DownloadError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=clean_error(str(exc))) from exc

    if not info:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not read media information.")

    raw_entries = [entry for entry in info.get("entries") or [] if entry]
    entries = [entry for entry in raw_entries if entry_video_url(entry)]
    if raw_entries and not entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This link does not contain downloadable videos. Paste a YouTube video or playlist URL.",
        )

    if entries:
        preview_entries = []
        for index, entry in enumerate(entries, start=1):
            duration = normalize_duration(entry.get("duration"))
            enforce_duration_limit(duration, settings.max_duration_seconds)
            entry_id = entry_video_id(entry) or str(index)
            preview_entries.append(
                PreviewEntry(
                    id=entry_id,
                    index=index,
                    title=entry.get("title") or f"Playlist item {index}",
                    webpageUrl=entry_video_url(entry),
                    thumbnail=entry_thumbnail(entry),
                    duration=duration,
                )
            )

        return PreviewResponse(
            kind="playlist",
            url=url,
            title=info.get("title") or "Untitled playlist",
            uploader=info.get("uploader") or info.get("channel"),
            thumbnail=entry_thumbnail(info),
            entries=preview_entries,
        )

    if not entry_video_url(info):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This link is not a downloadable YouTube video or playlist.",
        )

    duration = normalize_duration(info.get("duration"))
    enforce_duration_limit(duration, settings.max_duration_seconds)
    return PreviewResponse(
        kind="video",
        url=url,
        title=info.get("title") or "Untitled video",
        uploader=info.get("uploader") or info.get("channel"),
        thumbnail=entry_thumbnail(info),
        duration=duration,
        entries=[],
    )


def run_download_job(job: Job, manager: JobManager, settings: Settings) -> None:
    downloaded_files: List[Path] = []
    try:
        ensure_directory(job.temp_dir)
        download_dir = ensure_directory(job.temp_dir / "downloads")

        manager.update(job, status=JobState.metadata, message="Reading media information")
        targets = resolve_targets(job, settings)
        manager.update(job, total_items=len(targets), message="Starting download")

        for position, target in enumerate(targets, start=1):
            check_cancelled(job)
            title = target.get("title") or f"Item {position}"
            manager.update(
                job,
                status=JobState.downloading,
                current_item=title,
                completed_items=position - 1,
                message=f"Downloading {position} of {len(targets)}",
            )
            new_files = download_one(
                job,
                manager,
                settings,
                target["url"],
                download_dir,
                position,
                len(targets),
            )
            downloaded_files.extend(new_files)
            manager.update(job, completed_items=position, progress=(position / len(targets)) * 100)

        check_cancelled(job)
        media_files = stable_media_files(downloaded_files, download_dir)
        if not media_files:
            raise RuntimeError("Download completed, but no output file was created.")

        if len(media_files) > 1:
            manager.update(job, status=JobState.archiving, message="Creating ZIP archive")
            archive_name = safe_filename(f"{job.kind.value}-playlist.zip")
            output_path = zip_files(media_files, job.temp_dir / archive_name)
            manager.update(job, output_path=output_path, is_archive=True)
        else:
            manager.update(job, output_path=media_files[0], is_archive=False)

        manager.update(job, status=JobState.ready, progress=100, message="Ready to download")
    except DownloadCancelled:
        manager.update(job, status=JobState.cancelled, message="Cancelled")
    except Exception as exc:
        manager.update(job, status=JobState.failed, error=clean_error(str(exc)), message="Download failed")


def resolve_targets(job: Job, settings: Settings) -> List[Dict[str, str]]:
    info = extract_flat(job.url, settings)
    raw_entries = [entry for entry in info.get("entries") or [] if entry]
    entries = [entry for entry in raw_entries if entry_video_url(entry)]
    if raw_entries and not entries:
        raise RuntimeError("This link does not contain downloadable videos.")

    if not entries:
        video_url = entry_video_url(info)
        if not video_url:
            raise RuntimeError("This link is not a downloadable YouTube video.")
        duration = normalize_duration(info.get("duration"))
        enforce_duration_limit(duration, settings.max_duration_seconds)
        return [{"url": video_url, "title": info.get("title") or "Video"}]

    selected = set(job.entry_ids)
    if not selected:
        selected = {entry_video_id(entry) or str(index) for index, entry in enumerate(entries, start=1)}

    if len(selected) > settings.max_playlist_items:
        raise RuntimeError(f"Select at most {settings.max_playlist_items} playlist items.")

    targets = []
    for index, entry in enumerate(entries, start=1):
        entry_id = entry_video_id(entry) or str(index)
        if entry_id not in selected:
            continue
        duration = normalize_duration(entry.get("duration"))
        enforce_duration_limit(duration, settings.max_duration_seconds)
        video_url = entry_video_url(entry)
        if not video_url:
            continue
        targets.append(
            {
                "url": video_url,
                "title": entry.get("title") or f"Playlist item {index}",
            }
        )

    if not targets:
        raise RuntimeError("No selected playlist items were found.")
    return targets


def extract_flat(url: str, settings: Settings) -> Dict[str, Any]:
    opts = metadata_options(settings)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info or {}


def metadata_options(settings: Settings) -> Dict[str, Any]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ignore_no_formats_error": True,
    }
    opts.update(ytdlp_runtime_options())
    opts.update(ytdlp_auth_options(settings))
    return opts


def download_one(
    job: Job,
    manager: JobManager,
    settings: Settings,
    url: str,
    download_dir: Path,
    position: int,
    total: int,
) -> List[Path]:
    before = set(download_dir.glob("*"))
    opts = ytdlp_options(job, download_dir, settings)

    def progress_hook(data: Dict[str, Any]) -> None:
        check_cancelled(job)
        status_value = data.get("status")
        if status_value == "downloading":
            item_progress = progress_from_hook(data)
            overall = ((position - 1) + item_progress) / total * 100
            manager.update(
                job,
                status=JobState.downloading,
                progress=overall,
                message=progress_message(data, position, total),
            )
        elif status_value == "finished":
            manager.update(job, status=JobState.converting, message="Converting or merging media")

    def postprocessor_hook(data: Dict[str, Any]) -> None:
        check_cancelled(job)
        if data.get("status") == "started":
            manager.update(job, status=JobState.converting, message="Converting or merging media")

    opts["progress_hooks"] = [progress_hook]
    opts["postprocessor_hooks"] = [postprocessor_hook]

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    after = set(download_dir.glob("*"))
    created = [path for path in after - before if is_final_media(path)]
    if not created:
        created = [path for path in after if is_final_media(path)]
    return sorted(created, key=lambda path: path.stat().st_mtime)


def ytdlp_options(job: Job, download_dir: Path, settings: Settings) -> Dict[str, Any]:
    outtmpl = str(download_dir / "%(title).180B [%(id)s].%(ext)s")
    base: Dict[str, Any] = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "continuedl": True,
    }
    base.update(ytdlp_runtime_options())
    base.update(ytdlp_auth_options(settings))

    if job.kind.value == "mp3":
        preferred_quality = "320" if job.quality == "best" else job.quality.rstrip("k")
        base.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": preferred_quality,
                    }
                ],
            }
        )
        return base

    fmt = mp4_format_selector(job.quality)
    base.update({"format": fmt, "merge_output_format": "mp4"})
    return base


def mp4_format_selector(quality: str) -> str:
    if quality == "best":
        return "bestvideo*+bestaudio/best/bestaudio/bestvideo*"

    height = quality.rstrip("p")
    return (
        f"bestvideo*[height<={height}]+bestaudio/"
        f"best[height<={height}]/"
        "bestaudio/"
        f"bestvideo*[height<={height}]/"
        "best"
    )


def ytdlp_auth_options(settings: Settings) -> Dict[str, Any]:
    opts: Dict[str, Any] = {}
    if settings.ytdlp_cookie_file_path:
        opts["cookiefile"] = settings.ytdlp_cookie_file_path
    if settings.ytdlp_browser_cookie_spec:
        opts["cookiesfrombrowser"] = parse_cookies_from_browser(settings.ytdlp_browser_cookie_spec)
    return opts


def ytdlp_runtime_options() -> Dict[str, Any]:
    return {"js_runtimes": {"node": {}}}


def parse_cookies_from_browser(
    value: str,
) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    match = re.fullmatch(
        r"""(?x)
        (?P<name>[^+:]+)
        (?:\s*\+\s*(?P<keyring>[^:]+))?
        (?:\s*:\s*(?!:)(?P<profile>.+?))?
        (?:\s*::\s*(?P<container>.+))?
        """,
        value.strip(),
    )
    if match is None:
        raise ValueError(
            "APP_YTDLP_COOKIES_FROM_BROWSER must look like "
            "BROWSER[+KEYRING][:PROFILE][::CONTAINER], for example firefox or chrome:Default."
        )

    browser_name = match.group("name").strip().lower()
    if not browser_name:
        raise ValueError("APP_YTDLP_COOKIES_FROM_BROWSER must include a browser name.")

    profile = clean_optional_match(match.group("profile"))
    keyring = clean_optional_match(match.group("keyring"))
    container = clean_optional_match(match.group("container"))
    return browser_name, profile, keyring.upper() if keyring else None, container


def clean_optional_match(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def stable_media_files(files: Iterable[Path], download_dir: Path) -> List[Path]:
    candidates = [path for path in files if is_final_media(path)]
    if candidates:
        return sorted(set(candidates), key=lambda path: path.stat().st_mtime)
    return sorted([path for path in download_dir.glob("*") if is_final_media(path)], key=lambda path: path.stat().st_mtime)


def is_final_media(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name.endswith((".part", ".ytdl", ".temp")):
        return False
    return path.suffix.lower() in {".mp4", ".m4a", ".webm", ".mkv", ".mp3", ".opus"}


def normalize_duration(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def entry_thumbnail(info: Dict[str, Any]) -> Optional[str]:
    thumbnail = info.get("thumbnail")
    if thumbnail:
        return str(thumbnail)
    thumbnails = info.get("thumbnails") or []
    if thumbnails:
        return thumbnails[-1].get("url")
    return None


def entry_webpage_url(entry: Dict[str, Any]) -> Optional[str]:
    for key in ("webpage_url", "url"):
        value = entry.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    entry_id = entry.get("id")
    return youtube_watch_url(str(entry_id)) if entry_id else None


def entry_video_id(entry: Dict[str, Any]) -> Optional[str]:
    entry_id = entry.get("id")
    if is_youtube_video_id(str(entry_id) if entry_id else None):
        return str(entry_id)

    for key in ("webpage_url", "url"):
        value = entry.get(key)
        if isinstance(value, str):
            video_id = youtube_video_id_from_url(value)
            if video_id:
                return video_id
    return None


def entry_video_url(entry: Dict[str, Any]) -> Optional[str]:
    video_id = entry_video_id(entry)
    return youtube_watch_url(video_id) if video_id else None


def youtube_video_id_from_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    host = parsed.hostname.lower() if parsed.hostname else ""
    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)

    if host == "youtu.be":
        video_id = parsed.path.lstrip("/").split("/", 1)[0]
        return video_id if is_youtube_video_id(video_id) else None

    if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        return None

    if path == "/watch":
        video_id = query.get("v", [""])[0]
        return video_id if is_youtube_video_id(video_id) else None

    for prefix in ("/shorts/", "/live/", "/embed/"):
        if path.startswith(prefix):
            video_id = path.removeprefix(prefix).split("/", 1)[0]
            return video_id if is_youtube_video_id(video_id) else None

    return None


def youtube_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def progress_from_hook(data: Dict[str, Any]) -> float:
    total = data.get("total_bytes") or data.get("total_bytes_estimate")
    downloaded = data.get("downloaded_bytes")
    if total and downloaded:
        return max(0, min(1, float(downloaded) / float(total)))

    percent = data.get("_percent_str")
    if isinstance(percent, str):
        cleaned = re.sub(r"\x1b\[[0-9;]*m", "", percent).replace("%", "").strip()
        try:
            return max(0, min(1, float(cleaned) / 100))
        except ValueError:
            return 0
    return 0


def progress_message(data: Dict[str, Any], position: int, total: int) -> str:
    parts = [f"Downloading {position} of {total}"]
    speed = data.get("_speed_str")
    eta = data.get("_eta_str")
    if speed:
        parts.append(str(speed).strip())
    if eta:
        parts.append(f"ETA {str(eta).strip()}")
    return " - ".join(parts)


def check_cancelled(job: Job) -> None:
    if job.cancel_event.is_set():
        raise DownloadCancelled()


def clean_error(message: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", message)
    text = text.replace("ERROR:", "").strip()
    normalized = text.lower()
    if "sign in to confirm" in normalized and "not a bot" in normalized:
        return (
            "YouTube asked for sign-in/bot verification. Configure APP_YTDLP_COOKIE_FILE "
            "with exported browser cookies, or APP_YTDLP_COOKIES_FROM_BROWSER where available, then retry."
        )
    return text or "Something went wrong."
