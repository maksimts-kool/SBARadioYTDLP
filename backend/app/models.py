from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class MediaKind(str, Enum):
    mp4 = "mp4"
    mp3 = "mp3"


class JobState(str, Enum):
    queued = "queued"
    metadata = "metadata"
    downloading = "downloading"
    converting = "converting"
    archiving = "archiving"
    ready = "ready"
    failed = "failed"
    cancelled = "cancelled"


class PreviewRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class PreviewEntry(BaseModel):
    id: str
    index: int
    title: str
    webpageUrl: Optional[str] = None
    thumbnail: Optional[str] = None
    duration: Optional[int] = None


class PreviewResponse(BaseModel):
    kind: Literal["video", "playlist"]
    url: str
    title: str
    uploader: Optional[str] = None
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    entries: List[PreviewEntry] = Field(default_factory=list)


class JobCreateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    kind: MediaKind
    quality: str = Field(min_length=1, max_length=16)
    entryIds: List[str] = Field(default_factory=list, max_length=50)
    termsAccepted: bool = False


class JobStatusResponse(BaseModel):
    jobId: str
    status: JobState
    progress: float = 0
    currentItem: Optional[str] = None
    totalItems: int = 0
    completedItems: int = 0
    message: Optional[str] = None
    error: Optional[str] = None
    downloadUrl: Optional[str] = None
    isArchive: bool = False
    createdAt: datetime
    updatedAt: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
