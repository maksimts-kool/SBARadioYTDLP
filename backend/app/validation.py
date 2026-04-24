from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, status

ALLOWED_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}

MP4_QUALITIES = {"best", "1080p", "720p", "480p", "360p"}
MP3_QUALITIES = {"best", "320k", "192k", "128k"}
YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def validate_youtube_url(url: str) -> str:
    candidate = url.strip()
    parsed = urlparse(candidate)
    host = parsed.hostname.lower() if parsed.hostname else ""

    if parsed.scheme not in {"http", "https"} or host not in ALLOWED_YOUTUBE_HOSTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enter a valid YouTube URL.",
        )

    if not is_supported_youtube_media_url(candidate):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enter a YouTube video or playlist URL.",
        )

    return candidate


def is_supported_youtube_media_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname.lower() if parsed.hostname else ""
    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)

    if host == "youtu.be":
        video_id = parsed.path.lstrip("/").split("/", 1)[0]
        return is_youtube_video_id(video_id)

    if host not in ALLOWED_YOUTUBE_HOSTS:
        return False

    if get_first_query_value(query, "list"):
        return True

    if path == "/watch":
        return is_youtube_video_id(get_first_query_value(query, "v"))

    for prefix in ("/shorts/", "/live/", "/embed/"):
        if path.startswith(prefix):
            video_id = path.removeprefix(prefix).split("/", 1)[0]
            return is_youtube_video_id(video_id)

    return False


def is_youtube_video_id(value: Optional[str]) -> bool:
    return bool(value and YOUTUBE_VIDEO_ID_RE.fullmatch(value))


def get_first_query_value(query: dict[str, list[str]], key: str) -> Optional[str]:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def validate_quality(kind: str, quality: str) -> str:
    allowed = MP3_QUALITIES if kind == "mp3" else MP4_QUALITIES
    if quality not in allowed:
        choices = ", ".join(sorted(allowed))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported {kind.upper()} quality. Choose one of: {choices}.",
        )
    return quality


def enforce_duration_limit(duration: Optional[int], max_seconds: int) -> None:
    if duration is not None and duration > max_seconds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This item is longer than the configured duration limit.",
        )


def enforce_playlist_limit(entry_ids: Iterable[str], max_items: int) -> None:
    count = len(list(entry_ids))
    if count > max_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Select at most {max_items} playlist items.",
        )
