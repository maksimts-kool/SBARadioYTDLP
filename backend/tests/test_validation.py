from fastapi import HTTPException

from app.config import Settings
from app.storage import safe_filename
from app.validation import enforce_playlist_limit, validate_quality, validate_youtube_url


def test_validate_youtube_url_accepts_youtube_hosts():
    assert validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert validate_youtube_url("https://youtu.be/dQw4w9WgXcQ") == "https://youtu.be/dQw4w9WgXcQ"
    assert validate_youtube_url("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "https://www.youtube.com/shorts/dQw4w9WgXcQ"
    assert validate_youtube_url("https://www.youtube.com/playlist?list=PL123") == "https://www.youtube.com/playlist?list=PL123"


def test_validate_youtube_url_rejects_other_hosts():
    try:
        validate_youtube_url("https://example.com/watch?v=abc123")
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Expected HTTPException")


def test_validate_youtube_url_rejects_non_media_youtube_pages():
    for url in [
        "https://www.youtube.com/",
        "https://www.youtube.com/@channel/videos",
        "https://www.youtube.com/playlis",
        "https://www.youtube.com/watch?v=not-a-real-id",
        "https://youtu.be/not-a-real-id",
    ]:
        try:
            validate_youtube_url(url)
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError(f"Expected HTTPException for {url}")


def test_validate_quality_by_media_kind():
    assert validate_quality("mp4", "720p") == "720p"
    assert validate_quality("mp3", "192k") == "192k"


def test_validate_quality_rejects_wrong_kind():
    try:
        validate_quality("mp3", "720p")
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Expected HTTPException")


def test_enforce_playlist_limit():
    enforce_playlist_limit(["a", "b"], 2)
    try:
        enforce_playlist_limit(["a", "b", "c"], 2)
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Expected HTTPException")


def test_safe_filename_has_fallback():
    assert safe_filename("   ...   ") == "download"


def test_settings_splits_allowed_origins():
    settings = Settings(allowed_origins="http://localhost:5173, http://127.0.0.1:5173")
    assert settings.allowed_origin_list == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_settings_normalizes_allowed_origins():
    settings = Settings(allowed_origins="https://example.vercel.app/, https://other.vercel.app")
    assert settings.allowed_origin_list == ["https://example.vercel.app", "https://other.vercel.app"]


def test_settings_ignores_empty_origin_regex():
    settings = Settings(allowed_origin_regex=" ")
    assert settings.allowed_origin_regex_pattern is None
