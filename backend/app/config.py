from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    allowed_origin_regex: str = ""
    temp_root: Path = Path("/tmp/sbaradio-ytdlp")
    max_playlist_items: int = 50
    max_duration_seconds: int = 4 * 60 * 60
    max_active_jobs: int = 1
    cleanup_after_seconds: int = 60 * 60
    cleanup_interval_seconds: int = 10 * 60
    ytdlp_cookie_file: str = ""
    ytdlp_cookies_from_browser: str = ""
    redis_url: str = ""
    redis_healthcheck_timeout_seconds: float = 1.0
    redis_namespace: str = "sbaradio-ytdlp"
    redis_job_lock_ttl_seconds: int = 6 * 60 * 60
    admin_password: str = "admin"
    admin_session_ttl_seconds: int = 12 * 60 * 60
    admin_state_file: str = ""
    admin_history_limit: int = 200

    @property
    def allowed_origin_list(self) -> list[str]:
        return [normalize_origin(origin) for origin in self.allowed_origins.split(",") if normalize_origin(origin)]

    @property
    def allowed_origin_regex_pattern(self) -> str | None:
        pattern = self.allowed_origin_regex.strip()
        return pattern or None

    @property
    def ytdlp_cookie_file_path(self) -> str | None:
        path = self.ytdlp_cookie_file.strip()
        return path or None

    @property
    def ytdlp_browser_cookie_spec(self) -> str | None:
        spec = self.ytdlp_cookies_from_browser.strip()
        return spec or None

    @property
    def redis_connection_url(self) -> str | None:
        url = self.redis_url.strip()
        return url or None

    @property
    def admin_state_path(self) -> Path:
        path = self.admin_state_file.strip()
        return Path(path) if path else self.temp_root / "admin-state.json"


def normalize_origin(origin: str) -> str:
    cleaned = origin.strip()
    if cleaned == "*":
        return cleaned
    return cleaned.rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
