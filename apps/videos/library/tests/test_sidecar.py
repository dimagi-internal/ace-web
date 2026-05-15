import json

import pytest

from apps.videos.library.sidecar import (
    AudioSidecar,
    SidecarParseError,
    VideoSidecar,
    parse_audio_sidecar,
    parse_video_sidecar,
)


def test_video_sidecar_roundtrip():
    raw = json.dumps({
        "name": "Drone — village wide",
        "description": "Slow push-in at sunrise.",
        "tags": ["drone", "wide"],
    })
    sc = parse_video_sidecar(raw)
    assert sc == VideoSidecar(
        name="Drone — village wide",
        description="Slow push-in at sunrise.",
        tags=["drone", "wide"],
    )


def test_video_sidecar_description_optional():
    raw = json.dumps({"name": "x", "tags": []})
    sc = parse_video_sidecar(raw)
    assert sc.description is None
    assert sc.tags == []


def test_video_sidecar_missing_name_rejects():
    with pytest.raises(SidecarParseError):
        parse_video_sidecar(json.dumps({"tags": []}))


def test_video_sidecar_malformed_json_rejects():
    with pytest.raises(SidecarParseError):
        parse_video_sidecar("{not json}")


def test_audio_sidecar_roundtrip():
    raw = json.dumps({
        "voice_id": "abc",
        "model": "eleven_turbo_v2",
        "text": "Hello world.",
        "duration_sec": 1.5,
        "generated_at": "2026-05-15T18:23:11Z",
    })
    sc = parse_audio_sidecar(raw)
    assert sc == AudioSidecar(
        voice_id="abc",
        model="eleven_turbo_v2",
        text="Hello world.",
        duration_sec=1.5,
        generated_at="2026-05-15T18:23:11Z",
    )


def test_audio_sidecar_duration_optional():
    raw = json.dumps({
        "voice_id": "abc",
        "model": "m",
        "text": "t",
        "duration_sec": None,
        "generated_at": "2026-05-15T18:23:11Z",
    })
    sc = parse_audio_sidecar(raw)
    assert sc.duration_sec is None
