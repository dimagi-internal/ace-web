"""Tests for the plugin version checker."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from apps.system import version as version_module
from apps.system.version import REMOTE_VERSION_URL, check_version


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure each test starts with a clean module-level cache."""
    version_module._cache.clear()
    yield
    version_module._cache.clear()


class TestCheckVersion:
    def test_plugin_dir_not_found(self, tmp_path: Path):
        missing = tmp_path / "does-not-exist"
        with patch(
            "apps.system.version._fetch_remote_version", return_value="1.2.3"
        ) as mock_fetch:
            result = check_version(str(missing))

        assert result == {
            "plugin_found": False,
            "plugin_version": None,
            "remote_version": None,
            "update_available": None,
            "plugin_path": str(missing),
        }
        # When the plugin dir is missing we shouldn't even attempt the remote fetch.
        mock_fetch.assert_not_called()

    def test_local_older_than_remote(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        with patch("apps.system.version._fetch_remote_version", return_value="1.2.0"):
            result = check_version(str(tmp_path))

        assert result["plugin_found"] is True
        assert result["plugin_version"] == "1.0.0"
        assert result["remote_version"] == "1.2.0"
        assert result["update_available"] is True
        assert result["plugin_path"] == str(tmp_path)

    def test_local_matches_remote(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.2.0\n")

        with patch("apps.system.version._fetch_remote_version", return_value="1.2.0"):
            result = check_version(str(tmp_path))

        assert result["plugin_found"] is True
        assert result["plugin_version"] == "1.2.0"
        assert result["remote_version"] == "1.2.0"
        assert result["update_available"] is False

    def test_remote_fetch_failure(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        with patch("apps.system.version._fetch_remote_version", return_value=None):
            result = check_version(str(tmp_path))

        assert result["plugin_found"] is True
        assert result["plugin_version"] == "1.0.0"
        assert result["remote_version"] is None
        assert result["update_available"] is None

    def test_cache_hit_avoids_second_fetch(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        with patch(
            "apps.system.version._fetch_remote_version", return_value="1.2.0"
        ) as mock_fetch:
            first = check_version(str(tmp_path))
            second = check_version(str(tmp_path))

        assert mock_fetch.call_count == 1
        assert first["remote_version"] == "1.2.0"
        assert second["remote_version"] == "1.2.0"
        assert first["update_available"] is True
        assert second["update_available"] is True

    def test_cache_miss_after_expiry(self, tmp_path: Path):
        (tmp_path / "VERSION").write_text("1.0.0\n")

        # Prime the cache with a timestamp guaranteed to be past the TTL.
        # Using 0.0 is flaky on CI where time.monotonic() is < TTL early in
        # the process lifetime — compute an explicitly-expired timestamp.
        expired_ts = time.monotonic() - (version_module._CACHE_TTL_SECONDS + 1)
        version_module._cache["remote_version"] = ("0.9.0", expired_ts)

        with patch(
            "apps.system.version._fetch_remote_version", return_value="1.2.0"
        ) as mock_fetch:
            result = check_version(str(tmp_path))

        assert mock_fetch.call_count == 1
        assert result["remote_version"] == "1.2.0"

    def test_remote_url_constant(self):
        assert REMOTE_VERSION_URL == (
            "https://raw.githubusercontent.com/jjackson/ace/main/VERSION"
        )

    def test_local_version_is_stripped(self, tmp_path: Path):
        """Trailing whitespace/newlines in VERSION must be stripped before compare."""
        (tmp_path / "VERSION").write_text("  1.2.0  \n\n")

        with patch("apps.system.version._fetch_remote_version", return_value="1.2.0"):
            result = check_version(str(tmp_path))

        assert result["plugin_version"] == "1.2.0"
        assert result["update_available"] is False
