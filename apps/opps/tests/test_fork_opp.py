"""Tests for opp fork — POST /api/opps/<slug>/fork.

Fork semantic per ACE plugin's orchestrator-reference § Fork Points:
mint a new run-id under the SAME opp folder, carry the kept upstream
phase artifacts forward, leave per-opp state (opp.yaml, inputs/,
eval-calibration/, open-questions.md, connect-state.yaml) untouched.
"""
from unittest.mock import patch

import pytest
import yaml
from django.core.cache import cache
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


@pytest.fixture(autouse=True)
def _clear_drive_caches():
    """The CachedDriveClient stores DriveFile lookups in Django's cache,
    keyed by folder id. Across tests, FakeDriveClient counter resets to
    1, so a stale cached entry from a prior test will hand back DriveFile
    objects whose ids reference a previous fake's nodes — making the
    second test's ``list_files`` look empty. Flush between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def authed_client(db):
    User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(User.objects.get(email="jon@dimagi.com"))
    return c


def _source_tree() -> dict:
    """A realistic source opp at the multi-run layout. Per-opp resources
    (opp.yaml, inputs/, eval-calibration/, open-questions.md,
    connect-state.yaml) live above ``runs/`` and must NOT be duplicated
    by the fork. The single existing run carries phase folders for
    phase 1 + 2 plus a per-run decisions log."""
    return {
        "ACE": {
            "source-opp": {
                "opp.yaml": (
                    "display_name: Source Opp\n"
                    "slug: source-opp\n"
                    "created_at: 2026-04-01T10:00:00Z\n"
                ),
                "inputs": {
                    "pdd.md": "# PDD\n\nThe design.",
                },
                "eval-calibration": {
                    "known-issues.md": "# calibration",
                },
                "open-questions.md": "- accreting q1\n",
                "connect-state.yaml": "program_id: 42\n",
                "runs": {
                    "20260501-1200": {
                        "run_state.yaml": (
                            "opportunity: source-opp\n"
                            "run_id: 20260501-1200\n"
                            "current_phase: ocs-setup\n"
                            "current_step: ocs-agent-setup\n"
                            "last_actor: ace@dimagi-ai.com\n"
                            "last_actor_at: 2026-05-01T13:00:00Z\n"
                        ),
                        "1-design": {
                            "idea-to-pdd.md": "PDD body",
                            "idea-to-pdd-eval_verdict.yaml": "verdict: pass\n",
                        },
                        "2-commcare": {
                            "pdd-to-learn-app.md": "learn app summary",
                        },
                    },
                },
            },
        },
    }


# ── Core: per-run fork into the same opp ───────────────────────────


def test_fork_mints_new_run_under_same_opp(authed_client, db, monkeypatch):
    """Forking yields a new ``runs/<YYYYMMDD-HHMM>/`` under the source
    opp. The source opp folder is otherwise unchanged — same name, same
    siblings, same per-opp files."""
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    _freeze_now(monkeypatch, "20260510-1430")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"fork_at_phase": "commcare-setup"},
            content_type="application/json",
        )
    assert resp.status_code == 201, resp.content
    body = resp.json()["data"]
    assert body["slug"] == "source-opp"  # same opp
    assert body["run_id"] == "20260510-1430"

    # Source opp still has its single name; no fork-as-sibling-opp.
    children = {c.name for c in fake.list_files(ace_id)}
    assert children == {"source-opp"}

    runs_id = fake.folder_id("ACE/source-opp/runs")
    run_names = {c.name for c in fake.list_files(runs_id)}
    assert run_names == {"20260501-1200", "20260510-1430"}


def test_fork_does_not_create_opp_workspace_row(authed_client, db, monkeypatch):
    """Per-run fork must not produce a second OppWorkspace DB row — the
    existing opp's row stays the only owner of the slug."""
    before = OppWorkspace.objects.count()
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    _freeze_now(monkeypatch, "20260510-1430")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"fork_at_phase": "commcare-setup"},
            content_type="application/json",
        )
    assert resp.status_code == 201
    assert OppWorkspace.objects.count() == before


def test_fork_leaves_per_opp_resources_untouched(authed_client, db, monkeypatch):
    """opp.yaml, inputs/, eval-calibration/, open-questions.md,
    connect-state.yaml live above runs/ and must be neither copied nor
    mutated."""
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    opp_yaml_id = fake.file_id("ACE/source-opp/opp.yaml")
    open_q_id = fake.file_id("ACE/source-opp/open-questions.md")
    conn_state_id = fake.file_id("ACE/source-opp/connect-state.yaml")
    before_opp = fake.get_content(opp_yaml_id, "text/yaml").content
    before_open_q = fake.get_content(open_q_id, "text/markdown").content
    before_conn = fake.get_content(conn_state_id, "text/yaml").content

    _freeze_now(monkeypatch, "20260510-1430")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"fork_at_phase": "commcare-setup"},
            content_type="application/json",
        )
    assert resp.status_code == 201

    assert fake.get_content(opp_yaml_id, "text/yaml").content == before_opp
    assert fake.get_content(open_q_id, "text/markdown").content == before_open_q
    assert fake.get_content(conn_state_id, "text/yaml").content == before_conn


def test_fork_copies_only_pre_fork_phase_folders(authed_client, db, monkeypatch):
    """Forking at ``commcare-setup`` (ordinal 2) carries ``1-design/``
    forward and skips ``2-commcare/`` (the fork phase itself)."""
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    _freeze_now(monkeypatch, "20260510-1430")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"fork_at_phase": "commcare-setup"},
            content_type="application/json",
        )
    assert resp.status_code == 201

    new_run_id = fake.folder_id("ACE/source-opp/runs/20260510-1430")
    new_run_children = {c.name for c in fake.list_files(new_run_id)}
    assert "1-design" in new_run_children
    assert "2-commcare" not in new_run_children
    # The kept phase folder carries its files verbatim.
    one_design = fake.folder_id("ACE/source-opp/runs/20260510-1430/1-design")
    one_design_files = {c.name for c in fake.list_files(one_design)}
    assert one_design_files == {"idea-to-pdd.md", "idea-to-pdd-eval_verdict.yaml"}


def test_fork_synthesizes_run_state_with_phases_seeded(
    authed_client, db, monkeypatch,
):
    """The new run gets a fresh ``run_state.yaml`` with: opportunity,
    run_id, current_phase=fork, owner email, and a phases map seeded
    ``done`` for kept phases / ``pending`` for the fork phase onward."""
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    _freeze_now(monkeypatch, "20260510-1430")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"fork_at_phase": "commcare-setup"},
            content_type="application/json",
        )
    assert resp.status_code == 201

    state_id = fake.file_id(
        "ACE/source-opp/runs/20260510-1430/run_state.yaml"
    )
    body = fake.get_content(state_id, "text/yaml").content
    state = yaml.safe_load(body)
    assert state["opportunity"] == "source-opp"
    assert state["run_id"] == "20260510-1430"
    assert state["current_phase"] == "commcare-setup"
    assert state["initiated_by"] == "jon@dimagi.com"
    assert state["forked_from"]["run_id"] == "20260501-1200"
    # Phase 1 (kept) skills are done; phase 2 (fork) skills are pending.
    phases = state["phases"]
    assert phases["design-review"]["idea-to-pdd"] == "done"
    assert phases["commcare-setup"]["pdd-to-learn-app"] == "pending"


def test_fork_preserves_source_run_state(authed_client, db, monkeypatch):
    """The source run's run_state.yaml must NOT be touched — only the
    new run gets a freshly synthesized one."""
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    src_state_id = fake.file_id(
        "ACE/source-opp/runs/20260501-1200/run_state.yaml"
    )
    before = fake.get_content(src_state_id, "text/yaml").content

    _freeze_now(monkeypatch, "20260510-1430")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"fork_at_phase": "commcare-setup"},
            content_type="application/json",
        )
    assert resp.status_code == 201
    assert fake.get_content(src_state_id, "text/yaml").content == before


# ── decisions.yaml: copied + trimmed by phase ──────────────────────


def test_fork_trims_decisions_yaml_to_pre_fork_rows(
    authed_client, db, monkeypatch,
):
    """decisions.yaml is carried over from the source run with rows for
    phases >= the fork ordinal dropped. Per-row ``phase`` tag drives
    the filter."""
    tree = _source_tree()
    tree["ACE"]["source-opp"]["runs"]["20260501-1200"]["decisions.yaml"] = (
        "decisions:\n"
        "  - id: d1\n    phase: design-review\n    skill: idea-to-pdd\n"
        "    question: archetype?\n    default: A\n    status: applied\n"
        "  - id: d2\n    phase: commcare-setup\n    skill: pdd-to-learn-app\n"
        "    question: form layout?\n    default: B\n    status: applied\n"
        "  - id: d3\n    phase: ocs-setup\n    skill: ocs-agent-setup\n"
        "    question: prompt style?\n    default: C\n    status: applied\n"
    )
    fake = FakeDriveClient.from_tree(tree)
    ace_id = fake.folder_id("ACE")
    _freeze_now(monkeypatch, "20260510-1430")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"fork_at_phase": "commcare-setup"},
            content_type="application/json",
        )
    assert resp.status_code == 201

    dec_id = fake.file_id(
        "ACE/source-opp/runs/20260510-1430/decisions.yaml"
    )
    body = fake.get_content(dec_id, "text/yaml").content
    rows = yaml.safe_load(body)["decisions"]
    assert [r["id"] for r in rows] == ["d1"]


def test_fork_with_no_decisions_file_skips_trim(
    authed_client, db, monkeypatch,
):
    """Source runs without a decisions log produce a new run without one."""
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    _freeze_now(monkeypatch, "20260510-1430")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"fork_at_phase": "commcare-setup"},
            content_type="application/json",
        )
    assert resp.status_code == 201
    new_run_id = fake.folder_id("ACE/source-opp/runs/20260510-1430")
    new_run_children = {c.name for c in fake.list_files(new_run_id)}
    assert "decisions.yaml" not in new_run_children


# ── source_run_id selection ────────────────────────────────────────


def test_fork_explicit_source_run_id(authed_client, db, monkeypatch):
    """Naming a specific source_run_id forks from THAT run, not the
    latest. Useful when the workbench user is viewing an older run."""
    tree = _source_tree()
    # Add a second, newer run that forks should NOT pick when the older
    # run is named explicitly.
    tree["ACE"]["source-opp"]["runs"]["20260505-0900"] = {
        "run_state.yaml": "opportunity: source-opp\n",
        "1-design": {"newer-design.md": "newer"},
    }
    fake = FakeDriveClient.from_tree(tree)
    ace_id = fake.folder_id("ACE")
    _freeze_now(monkeypatch, "20260510-1430")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={
                "fork_at_phase": "commcare-setup",
                "source_run_id": "20260501-1200",
            },
            content_type="application/json",
        )
    assert resp.status_code == 201
    one_design = fake.folder_id("ACE/source-opp/runs/20260510-1430/1-design")
    files = {c.name for c in fake.list_files(one_design)}
    # Files from the older source run, not the newer one.
    assert "idea-to-pdd.md" in files
    assert "newer-design.md" not in files


def test_fork_run_id_collision_appends_suffix(
    authed_client, db, monkeypatch,
):
    """Two forks in the same minute don't collide — the second mints
    ``YYYYMMDD-HHMM-2``."""
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    # Pre-create a run folder with the about-to-be-minted run-id.
    runs_id = fake.folder_id("ACE/source-opp/runs")
    fake.create_folder(runs_id, "20260510-1430")
    _freeze_now(monkeypatch, "20260510-1430")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"fork_at_phase": "commcare-setup"},
            content_type="application/json",
        )
    assert resp.status_code == 201
    assert resp.json()["data"]["run_id"] == "20260510-1430-2"


# ── error paths ────────────────────────────────────────────────────


def test_fork_rejects_unknown_source(authed_client, db):
    fake = FakeDriveClient.from_tree({"ACE": {}})
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/no-such/fork",
            data={"fork_at_phase": "commcare-setup"},
            content_type="application/json",
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "source-not-found"


def test_fork_rejects_unknown_source_run_id(authed_client, db):
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={
                "fork_at_phase": "commcare-setup",
                "source_run_id": "9999-9999",
            },
            content_type="application/json",
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "source-run-not-found"


def test_fork_rejects_opp_with_no_runs(authed_client, db):
    """A source opp folder without any ``runs/`` subtree can't be
    forked — there's no prior run to seed from."""
    tree = {"ACE": {"source-opp": {"opp.yaml": "slug: source-opp\n"}}}
    fake = FakeDriveClient.from_tree(tree)
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"fork_at_phase": "commcare-setup"},
            content_type="application/json",
        )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "no-runs"


def test_fork_rejects_unknown_phase(authed_client, db):
    """Forking at a phase the skill registry doesn't know about must
    hard-fail. Silent degenerate-to-copy-everything would defeat the
    per-run fork contract — the next /ace:run would think every phase
    was done."""
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"fork_at_phase": "no-such-phase"},
            content_type="application/json",
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unknown-phase"


def test_fork_rejects_missing_phase(authed_client, db):
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={},
            content_type="application/json",
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid-phase"


# ── progress + status endpoint ─────────────────────────────────────


def test_fork_invokes_progress_callback(db, monkeypatch):
    """progress_cb sees counting → copying* → finalizing → done with
    a non-zero file total."""
    from apps.auth.models import User
    from apps.opps.opp_forker import fork_opp
    from apps.workspaces.models import Workspace

    User.objects.create(email="jon@dimagi.com", display_name="Jon")
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    ws = Workspace.objects.first()
    events: list[dict] = []
    fork_opp(
        drive=fake,
        ace_root_folder_id=ace_id,
        owner=User.objects.get(email="jon@dimagi.com"),
        source_slug="source-opp",
        fork_at_phase="commcare-setup",
        workspace=ws,
        progress_cb=events.append,
    )
    statuses = [e["status"] for e in events]
    assert statuses[0] == "counting"
    assert "copying" in statuses
    assert statuses[-1] == "done"
    copying = [e for e in events if e["status"] == "copying"]
    total = copying[0]["total"]
    assert total > 0
    assert events[-1]["copied"] == total


def test_fork_status_endpoint_returns_cached_progress(
    authed_client, db, monkeypatch,
):
    """After a fork POST completes, GET /fork/status returns the final
    progress payload keyed on (slug, source_run_id). Empty source_run_id
    matches forks that didn't pin a specific source run."""
    fake = FakeDriveClient.from_tree(_source_tree())
    ace_id = fake.folder_id("ACE")
    _freeze_now(monkeypatch, "20260510-1430")
    with patch("apps.opps.access.get_drive_client", return_value=fake), \
         patch("apps.opps.access.resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/source-opp/fork",
            data={"fork_at_phase": "commcare-setup"},
            content_type="application/json",
        )
    assert resp.status_code == 201

    status_resp = authed_client.get(
        "/api/opps/source-opp/fork/status?source_run_id=",
    )
    assert status_resp.status_code == 200
    data = status_resp.json()["data"]
    assert data["status"] == "done"
    assert data["new_run_id"] == "20260510-1430"


def test_fork_status_unknown_for_no_inflight_fork(authed_client, db):
    resp = authed_client.get(
        "/api/opps/source-opp/fork/status?source_run_id=",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "unknown"


# ── helpers ────────────────────────────────────────────────────────


def _freeze_now(monkeypatch, run_id: str) -> None:
    """Pin the run-id minted by fork_opp by patching the datetime it
    derives from. The fork formats ``now_utc`` as ``%Y%m%d-%H%M``;
    parsing the test's ``run_id`` back gives us a deterministic now."""
    import datetime as _dt

    parsed = _dt.datetime.strptime(run_id, "%Y%m%d-%H%M").replace(tzinfo=_dt.UTC)

    class _FrozenDateTime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return parsed.replace(tzinfo=None)
            return parsed

    monkeypatch.setattr("apps.opps.opp_forker._dt.datetime", _FrozenDateTime)
