"""Round-trip tests for apps.activity.schemas."""
from __future__ import annotations

from apps.activity.schemas import ActivityEntryOut, ActivityFeedOut


def test_chat_event_round_trip():
    entry = ActivityEntryOut(
        kind="chat",
        ts="2026-05-14T10:00:00+00:00",
        opp_slug="my-opp",
        step_skill="idea-to-pdd",
        title="Chat about something",
        session_slug="sess-abc",
        meta={"source": "web", "status": "active", "message_count": 5},
    )
    d = entry.model_dump()
    assert d["kind"] == "chat"
    assert d["meta"]["message_count"] == 5
    assert d["session_slug"] == "sess-abc"


def test_verdict_event_round_trip():
    entry = ActivityEntryOut(
        kind="verdict",
        ts="2026-05-14T11:00:00+00:00",
        opp_slug="my-opp",
        step_skill="app-build",
        title="PASS 85/100 — app-build",
        meta={"score": 85, "passed": True},
    )
    assert entry.session_slug is None
    assert entry.meta["passed"] is True


def test_activity_feed_out_empty():
    feed = ActivityFeedOut(items=[], total=0)
    assert feed.total == 0
    assert feed.items == []


def test_activity_feed_out_with_items():
    entry = ActivityEntryOut(
        kind="chat",
        ts="2026-05-14T10:00:00+00:00",
        title="A chat",
        meta={},
    )
    feed = ActivityFeedOut(items=[entry], total=1)
    d = feed.model_dump()
    assert d["total"] == 1
    assert len(d["items"]) == 1
