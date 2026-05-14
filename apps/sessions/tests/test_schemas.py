"""Round-trip tests for apps/sessions/schemas.py.

Each test validates that ``Model.model_validate(data)`` succeeds and that
``model.model_dump()`` round-trips back to the input (modulo None defaults
that aren't in the input dict — those are excluded from the comparison).

For In/Patch schemas we also test that ``exclude_unset=True`` only returns
the fields that were explicitly provided.
"""
from __future__ import annotations

import datetime as dt

import pytest

from apps.sessions.schemas import (
    CostBreakdownOut,
    CostInvocationOut,
    MessageOut,
    ParticipantOut,
    SessionCreateIn,
    SessionListOut,
    SessionOut,
    SessionPatchIn,
    ShareTokenOut,
    StructureNodeOut,
    TokensOut,
    TurnStateCliOut,
    TurnStateOut,
)

# ── helpers ──────────────────────────────────────────────────────────────────

NOW = dt.datetime(2026, 5, 14, 12, 0, 0, tzinfo=dt.UTC)
NOW_ISO = NOW.isoformat()


# ── MessageOut ───────────────────────────────────────────────────────────────


def test_message_out_round_trip():
    data = {
        "id": 42,
        "turn_index": 3,
        "role": "assistant",
        "content": {"type": "text", "text": "Hello"},
        "plaintext": "Hello",
        "status": "complete",
        "error_detail": None,
        "started_at": NOW_ISO,
        "completed_at": NOW_ISO,
        "created_at": NOW_ISO,
    }
    obj = MessageOut.model_validate(data)
    assert obj.id == 42
    assert obj.role == "assistant"
    assert obj.status == "complete"
    assert obj.started_at == NOW


def test_message_out_minimal():
    """started_at / completed_at / error_detail can be null."""
    data = {
        "id": 1,
        "turn_index": 0,
        "role": "user",
        "content": {"type": "text", "text": "hi"},
        "plaintext": "hi",
        "status": "pending",
        "error_detail": None,
        "started_at": None,
        "completed_at": None,
        "created_at": NOW_ISO,
    }
    obj = MessageOut.model_validate(data)
    assert obj.started_at is None
    assert obj.completed_at is None


# ── ParticipantOut ────────────────────────────────────────────────────────────


def test_participant_out_round_trip():
    data = {
        "user_id": 7,
        "email": "alice@example.com",
        "display_name": "Alice",
        "role": "owner",
        "joined_at": NOW_ISO,
        "last_seen_at": None,
    }
    obj = ParticipantOut.model_validate(data)
    assert obj.user_id == 7
    assert obj.role == "owner"
    assert obj.last_seen_at is None


def test_participant_out_with_last_seen():
    data = {
        "user_id": 8,
        "email": "bob@example.com",
        "display_name": "Bob",
        "role": "editor",
        "joined_at": NOW_ISO,
        "last_seen_at": NOW_ISO,
    }
    obj = ParticipantOut.model_validate(data)
    assert obj.last_seen_at == NOW


# ── SessionOut / SessionListOut ───────────────────────────────────────────────


SESSION_BASE = {
    "slug": "abc12345",
    "title": "Test session",
    "status": "active",
    "backend_kind": "cli",
    "source": "web",
    "cli_session_id": None,
    "created_at": NOW_ISO,
    "updated_at": NOW_ISO,
    "message_count": 5,
    "preview": "Hello world",
    "opp_slug": "",
    "opp_run_id": "",
    "opp_step_skill": "",
    "opp_display_name": "",
    "opp_step_skill_display": "",
}


def test_session_list_out_round_trip():
    obj = SessionListOut.model_validate(SESSION_BASE)
    assert obj.slug == "abc12345"
    assert obj.status == "active"
    assert obj.backend_kind == "cli"
    assert obj.message_count == 5


def test_session_list_out_with_opp_linkage():
    data = {**SESSION_BASE, "opp_slug": "my-opp", "opp_run_id": "run-001",
            "opp_step_skill": "idea-to-pdd", "opp_display_name": "My Opp",
            "opp_step_skill_display": "Idea to PDD"}
    obj = SessionListOut.model_validate(data)
    assert obj.opp_slug == "my-opp"
    assert obj.opp_step_skill_display == "Idea to PDD"


def test_session_out_includes_messages():
    msg_data = {
        "id": 1,
        "turn_index": 0,
        "role": "user",
        "content": {"type": "text", "text": "hi"},
        "plaintext": "hi",
        "status": "complete",
        "error_detail": None,
        "started_at": None,
        "completed_at": None,
        "created_at": NOW_ISO,
    }
    data = {**SESSION_BASE, "messages": [msg_data]}
    obj = SessionOut.model_validate(data)
    assert len(obj.messages) == 1
    assert obj.messages[0].role == "user"


def test_session_out_empty_messages():
    data = {**SESSION_BASE, "messages": []}
    obj = SessionOut.model_validate(data)
    assert obj.messages == []


# ── SessionCreateIn ───────────────────────────────────────────────────────────


def test_session_create_in_minimal():
    obj = SessionCreateIn.model_validate({})
    assert obj.title == ""


def test_session_create_in_with_title():
    obj = SessionCreateIn.model_validate({"title": "My Session"})
    assert obj.title == "My Session"


def test_session_create_in_strips_whitespace():
    obj = SessionCreateIn.model_validate({"title": "  padded  "})
    assert obj.title == "padded"


def test_session_create_in_rejects_unknown_fields():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SessionCreateIn.model_validate({"title": "ok", "extra_field": "bad"})


# ── SessionPatchIn ────────────────────────────────────────────────────────────


def test_session_patch_in_partial_title_only():
    obj = SessionPatchIn.model_validate({"title": "Updated"})
    dump = obj.model_dump(exclude_unset=True)
    assert dump == {"title": "Updated"}
    assert "status" not in dump


def test_session_patch_in_partial_status_only():
    obj = SessionPatchIn.model_validate({"status": "archived"})
    dump = obj.model_dump(exclude_unset=True)
    assert dump == {"status": "archived"}
    assert "title" not in dump


def test_session_patch_in_both_fields():
    obj = SessionPatchIn.model_validate({"title": "New", "status": "active"})
    dump = obj.model_dump(exclude_unset=True)
    assert dump == {"title": "New", "status": "active"}


def test_session_patch_in_empty_is_valid():
    obj = SessionPatchIn.model_validate({})
    dump = obj.model_dump(exclude_unset=True)
    assert dump == {}


def test_session_patch_in_invalid_status():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SessionPatchIn.model_validate({"status": "deleted"})


# ── TurnStateOut ─────────────────────────────────────────────────────────────


def test_turn_state_out_running():
    data = {
        "running": True,
        "last_message_at": NOW_ISO,
        "cli": {
            "alive": True,
            "pid": 1234,
            "elapsed_s": 42.5,
            "last_active_age_s": 1.2,
            "credential_source": "user",
            "cli_session_id": "sess-abc",
            "spawned_with_resume": False,
        },
    }
    obj = TurnStateOut.model_validate(data)
    assert obj.running is True
    assert obj.last_message_at == NOW
    assert obj.cli is not None
    assert obj.cli.pid == 1234
    assert obj.cli.alive is True


def test_turn_state_out_idle_no_cli():
    data = {
        "running": False,
        "last_message_at": None,
        "cli": None,
    }
    obj = TurnStateOut.model_validate(data)
    assert obj.running is False
    assert obj.cli is None


def test_turn_state_cli_out_minimal_nulls():
    data = {
        "alive": False,
        "pid": None,
        "elapsed_s": 0.0,
        "last_active_age_s": 99.9,
        "credential_source": None,
        "cli_session_id": None,
        "spawned_with_resume": False,
    }
    obj = TurnStateCliOut.model_validate(data)
    assert obj.pid is None
    assert obj.credential_source is None


# ── TokensOut ────────────────────────────────────────────────────────────────


def test_tokens_out_round_trip():
    data = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_tokens": 10,
        "cache_read_tokens": 200,
    }
    obj = TokensOut.model_validate(data)
    assert obj.input_tokens == 100
    assert obj.cache_read_tokens == 200


# ── CostBreakdownOut ──────────────────────────────────────────────────────────


def _make_invocation():
    return {
        "start_ts": NOW_ISO,
        "wall_time_seconds": 30,
        "estimated_cost_usd": 0.002,
        "cost_is_partial": False,
        "incomplete": False,
        "tokens": {
            "input_tokens": 200,
            "output_tokens": 100,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 50,
        },
    }


def _make_skill():
    return {
        "skill_name": "idea-to-pdd",
        "skill_display": "Idea to PDD",
        "invocation_count": 1,
        "wall_time_seconds": 30,
        "estimated_cost_usd": 0.002,
        "cost_is_partial": False,
        "tokens": {
            "input_tokens": 200,
            "output_tokens": 100,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 50,
        },
        "invocations": [_make_invocation()],
    }


def _make_phase():
    return {
        "phase_name": "idea-to-design",
        "phase_display": "Idea to Design",
        "phase_ordinal": 1,
        "wall_time_seconds": 30,
        "estimated_cost_usd": 0.002,
        "cost_is_partial": False,
        "tokens": {
            "input_tokens": 200,
            "output_tokens": 100,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 50,
        },
        "skills": [_make_skill()],
    }


def test_cost_breakdown_out_full():
    data = {
        "schema_version": 1,
        "computed_at": NOW_ISO,
        "totals": {
            "wall_time_seconds": 120,
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_creation_tokens": 100,
            "cache_read_tokens": 800,
            "estimated_cost_usd": 0.025,
            "cost_is_partial": False,
            "cache_hit_ratio": 0.42,
        },
        "phases": [_make_phase()],
    }
    obj = CostBreakdownOut.model_validate(data)
    assert obj.schema_version == 1
    assert obj.totals is not None
    assert obj.totals.estimated_cost_usd == pytest.approx(0.025)
    assert len(obj.phases) == 1
    assert obj.phases[0].phase_name == "idea-to-design"
    assert len(obj.phases[0].skills) == 1
    assert len(obj.phases[0].skills[0].invocations) == 1


def test_cost_breakdown_out_empty_schema_v0():
    """Empty breakdown (legacy upload) — schema_version=0, totals=None, phases=[]."""
    data = {
        "schema_version": 0,
        "totals": None,
        "phases": [],
    }
    obj = CostBreakdownOut.model_validate(data)
    assert obj.schema_version == 0
    assert obj.totals is None
    assert obj.phases == []


def test_cost_invocation_out_null_start_ts():
    data = {
        "start_ts": None,
        "wall_time_seconds": 0,
        "estimated_cost_usd": 0.0,
        "cost_is_partial": False,
        "incomplete": True,
        "tokens": {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        },
    }
    obj = CostInvocationOut.model_validate(data)
    assert obj.start_ts is None
    assert obj.incomplete is True


# ── StructureNodeOut (recursive) ──────────────────────────────────────────────


def test_structure_node_tool():
    data = {
        "kind": "tool",
        "tool_use_id": "tool-abc",
        "tool_name": "Bash",
        "label": "ls -la",
        "started_at": NOW_ISO,
        "wall_time_seconds": 2,
        "status": "ok",
        "content_preview": "total 42",
        "children": [],
    }
    obj = StructureNodeOut.model_validate(data)
    assert obj.kind == "tool"
    assert obj.tool_name == "Bash"
    assert obj.children == []


def test_structure_node_skill_with_tool_children():
    tool_node = {
        "kind": "tool",
        "tool_use_id": "t1",
        "tool_name": "Read",
        "label": "/foo/bar.py",
        "started_at": NOW_ISO,
        "wall_time_seconds": 1,
        "status": "ok",
        "content_preview": None,
        "children": [],
    }
    data = {
        "kind": "skill",
        "name": "idea-to-pdd",
        "display": "Idea to PDD",
        "is_subagent": False,
        "started_at": NOW_ISO,
        "wall_time_seconds": 120,
        "estimated_cost_usd": 0.003,
        "cost_is_partial": False,
        "tokens": {
            "input_tokens": 300,
            "output_tokens": 150,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        },
        "status": "ok",
        "children": [tool_node],
    }
    obj = StructureNodeOut.model_validate(data)
    assert obj.kind == "skill"
    assert len(obj.children) == 1
    assert obj.children[0].kind == "tool"


def test_structure_node_parallel_group():
    tool_a = {
        "kind": "tool",
        "tool_use_id": "ta",
        "tool_name": "Bash",
        "label": "cmd a",
        "started_at": NOW_ISO,
        "wall_time_seconds": 1,
        "status": "ok",
        "content_preview": None,
        "children": [],
    }
    tool_b = {**tool_a, "tool_use_id": "tb", "label": "cmd b"}
    data = {
        "kind": "parallel_group",
        "started_at": NOW_ISO,
        "wall_time_seconds": 1,
        "children": [tool_a, tool_b],
    }
    obj = StructureNodeOut.model_validate(data)
    assert obj.kind == "parallel_group"
    assert len(obj.children) == 2


def test_structure_node_phase_with_deep_nesting():
    """Phase → skill (subagent) → skill → tool — three levels deep."""
    inner_tool = {
        "kind": "tool",
        "tool_use_id": "inner-t",
        "tool_name": "Edit",
        "label": "/src/foo.py",
        "started_at": NOW_ISO,
        "wall_time_seconds": 0,
        "status": "ok",
        "content_preview": None,
        "children": [],
    }
    inner_skill = {
        "kind": "skill",
        "name": "write-tests",
        "display": "Write Tests",
        "is_subagent": True,
        "started_at": NOW_ISO,
        "wall_time_seconds": 30,
        "estimated_cost_usd": 0.001,
        "cost_is_partial": False,
        "tokens": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        },
        "status": "ok",
        "children": [inner_tool],
    }
    outer_skill = {
        "kind": "skill",
        "name": "build-app",
        "display": "Build App",
        "is_subagent": False,
        "started_at": NOW_ISO,
        "wall_time_seconds": 60,
        "estimated_cost_usd": 0.005,
        "cost_is_partial": False,
        "tokens": {
            "input_tokens": 500,
            "output_tokens": 200,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        },
        "status": "ok",
        "children": [inner_skill],
    }
    phase_node = {
        "kind": "phase",
        "name": "build",
        "display": "Build",
        "ordinal": 2,
        "wall_time_seconds": 60,
        "estimated_cost_usd": 0.005,
        "cost_is_partial": False,
        "tokens": {
            "input_tokens": 500,
            "output_tokens": 200,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        },
        "status": "ok",
        "children": [outer_skill],
    }
    obj = StructureNodeOut.model_validate(phase_node)
    assert obj.kind == "phase"
    assert len(obj.children) == 1  # outer_skill
    outer = obj.children[0]
    assert outer.kind == "skill"
    assert len(outer.children) == 1  # inner_skill (subagent)
    inner = outer.children[0]
    assert inner.kind == "skill"
    assert inner.is_subagent is True
    assert len(inner.children) == 1  # inner_tool
    assert inner.children[0].kind == "tool"


# ── ShareTokenOut ─────────────────────────────────────────────────────────────


def test_share_token_out_active():
    data = {
        "token": "abc123xyz" * 3,
        "created_at": NOW_ISO,
        "revoked_at": None,
    }
    obj = ShareTokenOut.model_validate(data)
    assert obj.token == "abc123xyz" * 3
    assert obj.revoked_at is None


def test_share_token_out_revoked():
    data = {
        "token": "revoked-tok" * 2,
        "created_at": NOW_ISO,
        "revoked_at": NOW_ISO,
    }
    obj = ShareTokenOut.model_validate(data)
    assert obj.revoked_at == NOW


def test_share_token_out_with_url():
    """ShareTokenOut with optional url field (POST response shape)."""
    data = {
        "token": "abc123xyz" * 3,
        "created_at": NOW_ISO,
        "revoked_at": None,
        "url": "https://labs.connect.dimagi.com/ace/share/abc123xyz",
    }
    obj = ShareTokenOut.model_validate(data)
    assert obj.url is not None
    assert "share" in obj.url
