"""ACE plugin version checker with cached remote lookups.

Reads the local ``VERSION`` file from the plugin directory and fetches
the latest published version from GitHub, caching the result for 60
minutes to avoid excessive network traffic.

No Django dependencies — testable in isolation.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

REMOTE_VERSION_URL = (
    "https://raw.githubusercontent.com/dimagi-internal/ace/main/VERSION"
)

# Module-level cache: {"remote_version": (version_str, monotonic_timestamp)}
# Exposed so tests can clear it.
_cache: dict[str, tuple[str, float]] = {}

_CACHE_TTL_SECONDS = 60 * 60  # 60 minutes


def _fetch_remote_version() -> str | None:
    """Fetch the remote VERSION file from GitHub.

    Returns the stripped version string, or ``None`` on any failure.
    """
    try:
        resp = httpx.get(REMOTE_VERSION_URL, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        return resp.text.strip()
    except Exception:
        logger.debug("Failed to fetch remote VERSION", exc_info=True)
        return None


def _get_remote_version() -> str | None:
    """Return the remote version, using the 60-minute cache when available."""
    cached = _cache.get("remote_version")
    if cached is not None:
        version_str, ts = cached
        if (time.monotonic() - ts) < _CACHE_TTL_SECONDS:
            return version_str

    remote = _fetch_remote_version()
    if remote is not None:
        _cache["remote_version"] = (remote, time.monotonic())
    return remote


def check_version(plugin_path: str) -> dict:
    """Check the ACE plugin version and compare to the latest remote release.

    Returns a dict with the shape::

        {
            "plugin_found": bool,
            "plugin_version": str | None,
            "remote_version": str | None,
            "update_available": bool | None,  # None = couldn't check
            "plugin_path": str,
        }
    """
    path = Path(plugin_path)
    version_file = path / "VERSION"

    if not path.is_dir():
        return {
            "plugin_found": False,
            "plugin_version": None,
            "remote_version": None,
            "update_available": None,
            "plugin_path": plugin_path,
        }

    try:
        local_version = version_file.read_text().strip()
    except OSError:
        return {
            "plugin_found": True,
            "plugin_version": None,
            "remote_version": None,
            "update_available": None,
            "plugin_path": plugin_path,
        }

    remote_version = _get_remote_version()

    if remote_version is None:
        update_available = None
    else:
        update_available = local_version != remote_version

    return {
        "plugin_found": True,
        "plugin_version": local_version,
        "remote_version": remote_version,
        "update_available": update_available,
        "plugin_path": plugin_path,
    }
