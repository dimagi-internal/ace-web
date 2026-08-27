"""Skill-granular fork points + feedback seeding.

Restores a capability lost when ``apps/opps/fork.py`` was deleted in the
multi-run simplification (2026-04-20). That implementation trimmed by
``steps/<NN>-<skill>/`` folders, a layout that no longer exists; the
current layout is ``<N>-<phase>/<skill>[_<role>].<ext>``, so attribution
now comes from the artifact manifest's ``producedBy`` map.

Fixture note: phase/skill names below come from the stub plugin registry
(``apps/opps/tests/fixtures/stub_plugin/``), not from production ACE.
"""
import dataclasses
import datetime as dt
from unittest.mock import MagicMock

import pytest
from django.test import override_settings

from apps.opps.opp_forker import (
    ForkOppError,
    _keep_artifact_for_skill_fork,
    _phase_folder_disposition,
    fork_opp,
)
from apps.opps.skills import ForkPoint, reset_cache, resolve_fork_point

STUB_PLUGIN = "apps/opps/tests/fixtures/stub_plugin"


@pytest.fixture(autouse=True)
def _stub_registry():
    with override_settings(ACE_PLUGIN_PATH=STUB_PLUGIN):
        reset_cache()
        yield
    reset_cache()


# ── resolve_fork_point ─────────────────────────────────────────────


def test_resolves_a_phase_to_its_ordinal():
    point = resolve_fork_point(phase="commcare-setup")
    assert point.phase == "commcare-setup"
    assert point.phase_ordinal == 2
    assert point.skill is None
    assert not point.is_skill_fork
    assert point.label() == "commcare-setup"


def test_resolves_a_skill_to_its_owning_phase():
    point = resolve_fork_point(skill="app-deploy")
    assert point.phase == "commcare-setup"
    assert point.phase_ordinal == 2  # same phase as the phase-fork above
    assert point.skill == "app-deploy"
    assert point.is_skill_fork
    assert point.label() == "app-deploy"


def test_unknown_names_raise_keyerror_naming_the_input():
    with pytest.raises(KeyError, match="no-such-phase"):
        resolve_fork_point(phase="no-such-phase")
    with pytest.raises(KeyError, match="no-such-skill"):
        resolve_fork_point(skill="no-such-skill")


def test_requires_exactly_one_spelling():
    with pytest.raises(ValueError):
        resolve_fork_point()
    with pytest.raises(ValueError):
        resolve_fork_point(phase="commcare-setup", skill="app-deploy")


# ── phase-folder disposition ───────────────────────────────────────


def test_phase_fork_skips_its_own_phase_whole():
    point = resolve_fork_point(phase="commcare-setup")  # ordinal 2
    assert _phase_folder_disposition("1-design-review", point) == "keep"
    assert _phase_folder_disposition("2-commcare", point) == "skip"
    assert _phase_folder_disposition("3-connect", point) == "skip"


def test_skill_fork_keeps_its_own_phase_partially():
    point = resolve_fork_point(skill="app-deploy")  # phase ordinal 2
    assert _phase_folder_disposition("1-design-review", point) == "keep"
    assert _phase_folder_disposition("2-commcare", point) == "partial"
    assert _phase_folder_disposition("3-connect", point) == "skip"


def test_non_phase_folders_are_never_trimmed_by_disposition():
    point = resolve_fork_point(phase="commcare-setup")
    # Run-id-shaped and unrecognized names aren't phase folders; the caller
    # filters them separately, so disposition must not claim them.
    assert _phase_folder_disposition("20260101-1000", point) == "keep"
    assert _phase_folder_disposition("scratch", point) == "keep"


# ── artifact attribution ───────────────────────────────────────────


def test_keeps_artifacts_from_skills_before_the_fork_skill():
    point = resolve_fork_point(skill="app-deploy")
    # pdd-to-learn-app runs before app-deploy in the stub's commcare phase.
    assert _keep_artifact_for_skill_fork("learn-app-summary.md", point) is True


def test_drops_artifacts_from_the_fork_skill_itself():
    point = resolve_fork_point(skill="app-deploy")
    assert _keep_artifact_for_skill_fork("deployment-summary.md", point) is False


def test_unattributed_artifacts_are_kept():
    """A file the manifest doesn't know about must survive.

    Real runs contain artifacts that don't follow the `<skill>_<role>`
    convention (e.g. `deliver-connect-coverage.md`). Copying one
    needlessly costs a Drive call; dropping it loses data the fork was
    supposed to preserve, so the fallback is deliberately KEEP.
    """
    point = resolve_fork_point(skill="app-deploy")
    assert _keep_artifact_for_skill_fork("some-hand-written-note.md", point) is True


# ── fork_opp integration ───────────────────────────────────────────


class _FakeFile:
    def __init__(self, id, name, mime_type, size=None):
        self.id = id
        self.name = name
        self.mime_type = mime_type
        self.size = size


FOLDER = "application/vnd.google-apps.folder"


def _fake_drive():
    """Source run with a phase-1 folder and a phase-2 folder holding one
    artifact from each of two skills in the stub's commcare phase."""
    files = {
        "ace-root": [_FakeFile("source-opp", "source-opp", FOLDER)],
        "source-opp": [_FakeFile("runs", "runs", FOLDER)],
        "runs": [_FakeFile("run-source", "20260101-1000", FOLDER)],
        "run-source": [
            _FakeFile("p1", "1-design-review", FOLDER),
            _FakeFile("p2", "2-commcare", FOLDER),
        ],
        "p1": [_FakeFile("a-pdd", "pdd.md", "text/markdown", size=10)],
        "p2": [
            # produced by pdd-to-learn-app (before app-deploy)
            _FakeFile("a-learn", "learn-app-summary.md", "text/markdown", size=10),
            # produced by app-deploy (the fork skill itself)
            _FakeFile("a-deploy", "deployment-summary.md", "text/markdown", size=10),
        ],
    }
    copied: list[str] = []
    ids = iter([f"new-{i}" for i in range(50)])
    drive = MagicMock()
    drive.list_files.side_effect = lambda fid: files.get(fid, [])
    drive.create_folder.side_effect = lambda parent, name: next(ids)

    def _copy(src_id, dest_parent, name):
        copied.append(name)
        return next(ids)

    drive.copy_file.side_effect = _copy
    drive.get_text.side_effect = lambda fid: ""
    drive.update_file.side_effect = lambda fid, body, mime: fid
    drive.upload_file.side_effect = lambda parent, name, body, mime: next(ids)
    drive.create_file.side_effect = lambda parent, name, body, mime: next(ids)
    return drive, copied


def _stub_side_effects(monkeypatch, messages):
    monkeypatch.setattr(
        "apps.opps.opp_forker._build_run_state_yaml", lambda **kw: "stub: state\n",
    )
    monkeypatch.setattr(
        "apps.opps.opp_forker.Session.create_with_owner",
        classmethod(lambda cls, **kw: MagicMock(id=1, pk=1, slug="sess")),
    )
    monkeypatch.setattr(
        "apps.opps.opp_forker.Message.objects.create",
        lambda **kw: messages.append(kw) or MagicMock(),
    )


def _run_fork(monkeypatch, **kwargs):
    drive, copied = _fake_drive()
    messages: list[dict] = []
    _stub_side_effects(monkeypatch, messages)
    result = fork_opp(
        drive=drive,
        ace_root_folder_id="ace-root",
        owner=MagicMock(email="dev@example.com"),
        source_slug="source-opp",
        source_run_id="20260101-1000",
        now=dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.UTC),
        **kwargs,
    )
    return result, copied, messages


def test_phase_fork_drops_the_whole_fork_phase(monkeypatch):
    _, copied, _ = _run_fork(monkeypatch, fork_at_phase="commcare-setup")
    assert "pdd.md" in copied
    assert "learn-app-summary.md" not in copied
    assert "deployment-summary.md" not in copied


def test_skill_fork_keeps_earlier_artifacts_in_the_fork_phase(monkeypatch):
    """The capability the deleted fork.py had, on the current layout."""
    _, copied, _ = _run_fork(monkeypatch, fork_at_skill="app-deploy")
    assert "pdd.md" in copied                    # earlier phase, whole
    assert "learn-app-summary.md" in copied      # earlier skill, kept
    assert "deployment-summary.md" not in copied  # the fork skill, re-runs


def test_feedback_is_seeded_as_the_first_user_turn(monkeypatch):
    _, _, messages = _run_fork(
        monkeypatch, fork_at_skill="app-deploy", feedback="redeploy against the new CCZ",
    )
    user_turns = [m for m in messages if m.get("role") == "user"]
    assert len(user_turns) == 1
    assert user_turns[0]["plaintext"] == "redeploy against the new CCZ"
    assert user_turns[0]["turn_index"] == 1  # after the system turn


def test_no_feedback_seeds_no_user_turn(monkeypatch):
    _, _, messages = _run_fork(monkeypatch, fork_at_phase="commcare-setup")
    assert [m for m in messages if m.get("role") == "user"] == []


def test_system_message_records_which_spelling_was_used(monkeypatch):
    _, _, messages = _run_fork(monkeypatch, fork_at_skill="app-deploy")
    system = next(m for m in messages if m.get("role") == "system")
    assert system["content"]["fork_at_skill"] == "app-deploy"
    assert system["content"]["fork_at_phase"] == "commcare-setup"
    assert "skill `app-deploy`" in system["plaintext"]


def test_rejects_neither_or_both_fork_points(monkeypatch):
    with pytest.raises(ForkOppError) as exc:
        _run_fork(monkeypatch)
    assert exc.value.code == "invalid-fork-point"

    with pytest.raises(ForkOppError) as exc:
        _run_fork(monkeypatch, fork_at_phase="commcare-setup", fork_at_skill="app-deploy")
    assert exc.value.code == "invalid-fork-point"


def test_unknown_skill_reports_unknown_skill_not_unknown_phase(monkeypatch):
    """Error code names what the caller actually got wrong."""
    with pytest.raises(ForkOppError) as exc:
        _run_fork(monkeypatch, fork_at_skill="not-a-skill")
    assert exc.value.code == "unknown-skill"
    assert "not-a-skill" in str(exc.value)


def test_unknown_phase_still_reports_unknown_phase(monkeypatch):
    with pytest.raises(ForkOppError) as exc:
        _run_fork(monkeypatch, fork_at_phase="not-a-phase")
    assert exc.value.code == "unknown-phase"


def test_count_matches_copy_on_a_skill_fork(monkeypatch):
    """The progress total must equal what actually gets copied.

    They're computed by two different walks; if they diverge the progress
    bar lies (or divides by a wrong total). Both go through the same
    keep-predicate, and this pins that.
    """
    drive, copied = _fake_drive()
    messages: list[dict] = []
    _stub_side_effects(monkeypatch, messages)
    seen: list[dict] = []
    fork_opp(
        drive=drive,
        ace_root_folder_id="ace-root",
        owner=MagicMock(email="dev@example.com"),
        source_slug="source-opp",
        source_run_id="20260101-1000",
        fork_at_skill="app-deploy",
        progress_cb=seen.append,
        now=dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.UTC),
    )
    done = [e for e in seen if e.get("status") == "done"][-1]
    assert done["files_total"] == done["files_copied"] == len(copied)


def test_forkpoint_is_hashable_and_frozen():
    # It's threaded through closures in the copy walk; accidental mutation
    # mid-walk would change trim behaviour partway through a fork.
    point = ForkPoint(phase="p", phase_ordinal=1)
    assert hash(point)  # frozen dataclasses are hashable
    with pytest.raises(dataclasses.FrozenInstanceError):
        point.phase_ordinal = 2  # type: ignore[misc]
