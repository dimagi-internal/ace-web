"""Thin cache wrappers for the videos surface.

Reuses ``django.core.cache`` (already wired to Redis in
``config/settings/base.py``) — DRY with the rest of ace-web. No bespoke
Redis client, no custom JSON serialisation; Django's cache pickles
values for us. Apps/opps + apps/activity + apps/mobile all use the
same primitive.

Cache keys live under one ``videos:`` namespace so a workspace flush
or test reset is one ``delete_many`` call.

    videos:spec:<ws-slug>:<program-slug>:<run-id>   → spec.yaml text
    videos:runs:<ws-slug>:<program-slug>            → list[str] of run-ids
    videos:slugs:<ws-slug>                          → list[str] of program slugs

TTL fallback (60s) covers the rare case where a write skips the
invalidation step — e.g. someone edits a Drive file directly without
going through the API. Strict correctness via the Drive Changes API
can be a follow-up if drift becomes a real problem.
"""
from __future__ import annotations

from django.core.cache import cache as _cache


_TTL_SECONDS = 60


def _spec_key(ws_slug: str, slug: str, run_id: str) -> str:
    return f"videos:spec:{ws_slug}:{slug}:{run_id}"


def _runs_key(ws_slug: str, slug: str) -> str:
    return f"videos:runs:{ws_slug}:{slug}"


def _slugs_key(ws_slug: str) -> str:
    return f"videos:slugs:{ws_slug}"


# ---------------------------------------------------------------------------
# Spec content
# ---------------------------------------------------------------------------


def get_spec(ws_slug: str, slug: str, run_id: str) -> str | None:
    return _cache.get(_spec_key(ws_slug, slug, run_id))


def set_spec(ws_slug: str, slug: str, run_id: str, content: str) -> None:
    _cache.set(_spec_key(ws_slug, slug, run_id), content, _TTL_SECONDS)


def invalidate_spec(ws_slug: str, slug: str, run_id: str) -> None:
    _cache.delete(_spec_key(ws_slug, slug, run_id))


# ---------------------------------------------------------------------------
# Runs / program lists
# ---------------------------------------------------------------------------


def get_runs(ws_slug: str, slug: str) -> list[str] | None:
    return _cache.get(_runs_key(ws_slug, slug))


def set_runs(ws_slug: str, slug: str, ids: list[str]) -> None:
    _cache.set(_runs_key(ws_slug, slug), ids, _TTL_SECONDS)


def invalidate_runs(ws_slug: str, slug: str) -> None:
    _cache.delete(_runs_key(ws_slug, slug))


def get_slugs(ws_slug: str) -> list[str] | None:
    return _cache.get(_slugs_key(ws_slug))


def set_slugs(ws_slug: str, slugs: list[str]) -> None:
    _cache.set(_slugs_key(ws_slug), slugs, _TTL_SECONDS)


def invalidate_slugs(ws_slug: str) -> None:
    _cache.delete(_slugs_key(ws_slug))


# ---------------------------------------------------------------------------
# Bulk invalidation
# ---------------------------------------------------------------------------


def invalidate_program(ws_slug: str, slug: str) -> None:
    """Drop every key for one program: workspace slug list, the
    program's runs list, and every per-run spec across runs."""
    invalidate_slugs(ws_slug)
    invalidate_runs(ws_slug, slug)
    # django-redis exposes delete_pattern via _cache.delete_pattern;
    # locmem (used in tests) doesn't. Fall back to a no-op there —
    # the TTL is short enough that stale entries don't matter much
    # in test scope.
    delete_pattern = getattr(_cache, "delete_pattern", None)
    if callable(delete_pattern):
        delete_pattern(f"videos:spec:{ws_slug}:{slug}:*")


def invalidate_all_for_workspace(ws_slug: str) -> None:
    delete_pattern = getattr(_cache, "delete_pattern", None)
    if callable(delete_pattern):
        delete_pattern(f"videos:spec:{ws_slug}:*")
        delete_pattern(f"videos:runs:{ws_slug}:*")
    _cache.delete(_slugs_key(ws_slug))


# ---------------------------------------------------------------------------
# Media library
# ---------------------------------------------------------------------------


def _lib_video_key(ws_slug: str) -> str:
    return f"videos:lib:video:{ws_slug}"


def _lib_audio_key(ws_slug: str) -> str:
    return f"videos:lib:audio:{ws_slug}"


def get_lib_video(ws_slug: str):
    return _cache.get(_lib_video_key(ws_slug))


def set_lib_video(ws_slug: str, value) -> None:
    _cache.set(_lib_video_key(ws_slug), value, _TTL_SECONDS)


def invalidate_lib_video(ws_slug: str) -> None:
    _cache.delete(_lib_video_key(ws_slug))


def get_lib_audio(ws_slug: str):
    return _cache.get(_lib_audio_key(ws_slug))


def set_lib_audio(ws_slug: str, value) -> None:
    _cache.set(_lib_audio_key(ws_slug), value, _TTL_SECONDS)


def invalidate_lib_audio(ws_slug: str) -> None:
    _cache.delete(_lib_audio_key(ws_slug))
