import pytest

from app.config import Settings
from app.downloader import (
    clean_error,
    entry_video_url,
    parse_cookies_from_browser,
    metadata_options,
    ytdlp_auth_options,
    ytdlp_options,
)
from app.jobs import Job
from app.models import MediaKind


def test_entry_video_url_accepts_video_entries():
    assert entry_video_url({"id": "dQw4w9WgXcQ"}) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert entry_video_url({"url": "https://www.youtube.com/shorts/dQw4w9WgXcQ"}) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_entry_video_url_rejects_channel_tab_entries():
    assert entry_video_url({"id": "videos", "url": "https://www.youtube.com/@channel/videos"}) is None
    assert entry_video_url({"title": "Recommended", "url": "https://www.youtube.com/"}) is None


def test_ytdlp_auth_options_uses_cookie_file():
    settings = Settings(ytdlp_cookie_file=" /cookies/youtube.txt ")

    assert ytdlp_auth_options(settings) == {"cookiefile": "/cookies/youtube.txt"}


def test_ytdlp_auth_options_parses_cookies_from_browser():
    settings = Settings(
        ytdlp_cookie_file="",
        ytdlp_cookies_from_browser=" Chrome+gnomekeyring:Profile 1 ",
    )

    assert ytdlp_auth_options(settings) == {
        "cookiesfrombrowser": ("chrome", "Profile 1", "GNOMEKEYRING", None)
    }


def test_parse_cookies_from_browser_supports_firefox_container():
    assert parse_cookies_from_browser("firefox:default::none") == (
        "firefox",
        "default",
        None,
        "none",
    )


def test_parse_cookies_from_browser_rejects_invalid_spec():
    with pytest.raises(ValueError, match="APP_YTDLP_COOKIES_FROM_BROWSER"):
        parse_cookies_from_browser("chrome+")


def test_ytdlp_options_includes_cookie_auth(tmp_path):
    job = Job(
        id="job",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        kind=MediaKind.mp4,
        quality="best",
        entry_ids=[],
        temp_dir=tmp_path,
    )

    opts = ytdlp_options(job, tmp_path, Settings(ytdlp_cookie_file="/cookies/youtube.txt"))

    assert opts["cookiefile"] == "/cookies/youtube.txt"
    assert opts["format"] == "bv*+ba/b"


def test_metadata_options_ignore_missing_formats_for_preview():
    opts = metadata_options(Settings(ytdlp_cookie_file="/cookies/youtube.txt"))

    assert opts["cookiefile"] == "/cookies/youtube.txt"
    assert opts["skip_download"] is True
    assert opts["ignore_no_formats_error"] is True


def test_clean_error_guides_bot_check_to_cookie_settings():
    message = (
        "ERROR: [youtube] abc: Sign in to confirm you're not a bot. "
        "Use --cookies-from-browser or --cookies."
    )

    assert clean_error(message) == (
        "YouTube asked for sign-in/bot verification. Configure APP_YTDLP_COOKIE_FILE "
        "with exported browser cookies, or APP_YTDLP_COOKIES_FROM_BROWSER where available, then retry."
    )
