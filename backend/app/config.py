from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    temp_root: Path = Path("/tmp/sbaradio-ytdlp")
    max_playlist_items: int = 50
    max_duration_seconds: int = 4 * 60 * 60
    max_active_jobs: int = 1
    cleanup_after_seconds: int = 60 * 60
    cleanup_interval_seconds: int = 10 * 60

    @property
    def allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
