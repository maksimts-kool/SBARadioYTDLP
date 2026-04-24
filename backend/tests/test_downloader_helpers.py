from app.downloader import entry_video_url


def test_entry_video_url_accepts_video_entries():
    assert entry_video_url({"id": "dQw4w9WgXcQ"}) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert entry_video_url({"url": "https://www.youtube.com/shorts/dQw4w9WgXcQ"}) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_entry_video_url_rejects_channel_tab_entries():
    assert entry_video_url({"id": "videos", "url": "https://www.youtube.com/@channel/videos"}) is None
    assert entry_video_url({"title": "Recommended", "url": "https://www.youtube.com/"}) is None

