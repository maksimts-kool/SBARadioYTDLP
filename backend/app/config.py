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

    @property
    def allowed_origin_list(self) -> list[str]:
        return [normalize_origin(origin) for origin in self.allowed_origins.split(",") if normalize_origin(origin)]

    @property
    def allowed_origin_regex_pattern(self) -> str | None:
        pattern = self.allowed_origin_regex.strip()
        return pattern or None


def normalize_origin(origin: str) -> str:
    cleaned = origin.strip()
    if cleaned == "*":
        return cleaned
    return cleaned.rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
