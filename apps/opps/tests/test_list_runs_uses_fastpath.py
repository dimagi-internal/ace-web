"""The wiring test: DriveRunStore must actually TAKE the fast path here.

canopy_agent_runs negotiates `find_in_folders` / `get_contents` off the
client with getattr(). Both the real client and the cache wrapper implement
them — but a getattr() contract fails SILENTLY. If a rename, a refactor, or a
wrapper that forgets to re-expose them lands, the store quietly reverts to
1+2N sequential calls and the only symptom is that the page is slow again.

This test fails loudly instead.
"""
from __future__ import annotations

from apps.opps.drive_cache import CachedDriveClient
from apps.opps.drive_client import GoogleDriveClient


def test_the_real_client_offers_both_fast_paths():
    for name in ("find_in_folders", "get_contents"):
        assert callable(getattr(GoogleDriveClient, name, None)), (
            f"GoogleDriveClient.{name} is what DriveRunStore negotiates for; "
            "without it list_runs reverts to 1+2N sequential Drive calls"
        )


def test_the_cache_wrapper_re_exposes_them():
    """The wrapper is what the store actually receives. If only the inner
    client had these, the optimisation would be installed but inert."""
    for name in ("find_in_folders", "get_contents"):
        assert callable(getattr(CachedDriveClient, name, None)), (
            f"CachedDriveClient.{name} missing — the store sees the WRAPPER, "
            "so the fast path would never be taken"
        )


def test_the_installed_store_knows_how_to_use_them():
    """Guards the pin: ace-web can implement the methods perfectly and still
    get the slow path if canopy-agent-runs is pinned to a version that never
    asks for them."""
    import inspect

    from canopy_agent_runs.drive.store import DriveRunStore

    src = inspect.getsource(DriveRunStore)
    assert "find_in_folders" in src, (
        "the pinned canopy-agent-runs does not negotiate find_in_folders — "
        "check the tag in pyproject.toml"
    )
    assert "get_contents" in src, (
        "the pinned canopy-agent-runs does not negotiate get_contents — "
        "check the tag in pyproject.toml"
    )
