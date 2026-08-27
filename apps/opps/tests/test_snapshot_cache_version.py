"""The snapshot cache key must change when reader OUTPUT changes.

`_KEY_VERSION` guards against serving snapshots built by older code. Its
documented triggers were the cached dataclass *shape* and file_id
tracking semantics — both structural. The framework-reader migration
changed neither: same dataclasses, same tracking, but different artifact
ATTRIBUTION (which files land on which step). Nothing tripped, v7
entries survived, and opps cached before the migration kept serving the
old artifact list indefinitely — the changes feed can't help, because
the Drive files never changed. The CODE did.

Measured 2026-08-14 (issue #716), same deploy, same endpoint:
  spark-facilitator (cached July): open-questions.md, decisions.yaml, idea-to-pdd.md
  bednet-check-2-visit (cached today): idea-to-pdd-eval_verdict.yaml, idea-to-pdd.md

This test doesn't try to detect reader changes automatically — it can't.
It pins the version so a bump is a deliberate, reviewed edit, and keeps
the ledger of why each bump happened next to the constant.
"""
from apps.opps import snapshot_cache


def test_key_version_is_pinned():
    """Change this deliberately, and add a ledger line saying why."""
    assert snapshot_cache._KEY_VERSION == "v9"


def test_every_cache_key_carries_the_version():
    """A key that forgets the version silently outlives its bump."""
    keys = [
        snapshot_cache._snap_key("ws", "slug", "run"),
        snapshot_cache._card_key("ws", "slug"),
        snapshot_cache._idx_key("file-id"),
        snapshot_cache._ws_key("ws"),
    ]
    for k in keys:
        assert f":{snapshot_cache._KEY_VERSION}:" in k, k


def test_the_version_ledger_documents_the_current_version():
    """The comment block above the constant is the only record of WHY."""
    import inspect

    src = inspect.getsource(snapshot_cache)
    head = src.split("_KEY_VERSION =")[0]
    assert f"#   {snapshot_cache._KEY_VERSION} —" in head, (
        "bumped _KEY_VERSION without adding its ledger line"
    )
