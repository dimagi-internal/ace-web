"""Per-file JSON sidecar schemas.

Every media file under ``library/{video,audio}/`` has a sibling sidecar
file with the same stem (``foo.mp4`` ↔ ``foo.json``;
``<hash>.mp3`` ↔ ``<hash>.json``). The two media types carry different
metadata; the storage pattern is identical.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class SidecarParseError(ValueError):
    """Raised when a sidecar JSON is malformed or missing required fields."""


class VideoSidecar(BaseModel):
    """Human-curated metadata for a video clip in the library."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    tags: list[str]
    description: str | None = None


class AudioSidecar(BaseModel):
    """Machine-captured metadata for a TTS-synthesized audio clip."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    voice_id: str
    model: str
    text: str
    duration_sec: float | None
    generated_at: str


def _load_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SidecarParseError(f"malformed sidecar JSON: {e}") from e
    if not isinstance(data, dict):
        raise SidecarParseError(f"sidecar must be a JSON object, got {type(data).__name__}")
    return data


def parse_video_sidecar(raw: str) -> VideoSidecar:
    data = _load_json(raw)
    try:
        return VideoSidecar(**data)
    except ValidationError as e:
        raise SidecarParseError(str(e)) from e


def parse_audio_sidecar(raw: str) -> AudioSidecar:
    data = _load_json(raw)
    try:
        return AudioSidecar(**data)
    except ValidationError as e:
        raise SidecarParseError(str(e)) from e
