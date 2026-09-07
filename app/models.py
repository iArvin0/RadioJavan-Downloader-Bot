from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class MediaCandidate:
    url: str
    quality: str
    media_type: str
    extension: str
    content_length: int | None = None


@dataclass(slots=True)
class TrackInfo:
    input_url: str
    resolved_url: str
    media_id: str
    media_type: str
    title: str
    artist: str | None = None
    album: str | None = None
    duration: int | None = None
    cover_url: str | None = None
    page_url: str | None = None
    candidates: list[MediaCandidate] = field(default_factory=list)


@dataclass(slots=True)
class DownloadedMedia:
    path: Path
    track: TrackInfo
    candidate: MediaCandidate
