"""Pin _build_steps' step-status inference.

Primary source of truth is the declared status in run_state.yaml
(``phases.<phase>.steps.<skill>.status``). The plugin patches that
file on every step transition, and Drive Changes API reports the
edits reliably (it's an existing file_id, not a new child file), so
the OppSnapshot cache invalidates correctly and live runs surface
fresh progress.

Falls back to artifact-presence when run_state.yaml has no declared
status for a step — covers legacy runs and clients that pass no
run_state at all.
"""
from dataclasses import dataclass

from apps.opps.sync import ArtifactRef, _build_steps, _extract_step_statuses


@dataclass
class _StubSkill:
    name: str
    phase: str = "idea-to-design"
    ordinal: int = 1


def _artifact(name: str, path: str | None = None) -> ArtifactRef:
    return ArtifactRef(
        name=name,
        drive_file_id=f"id-{name}",
        drive_web_link="",
        size_bytes=0,
        mime_type="application/octet-stream",
        path=path or name,
    )


# --- Artifact-presence fallback (run_state.yaml absent / no status field) ---


def test_step_with_real_output_artifact_is_complete():
    """A skill that produced its own non-substrate artifact is complete."""
    skills = [_StubSkill("idea-to-pdd")]
    arts = {"idea-to-pdd": [_artifact("idea-to-pdd.md")]}
    [step] = _build_steps(skills, arts, {}, "folder-id")
    assert step.step.status == "complete"


def test_step_with_only_decisions_yaml_is_pending():
    """decisions.yaml carried over from a fork shouldn't fake completion."""
    skills = [_StubSkill("idea-to-pdd")]
    arts = {"idea-to-pdd": [_artifact("decisions.yaml")]}
    [step] = _build_steps(skills, arts, {}, "folder-id")
    assert step.step.status == "pending"


def test_step_with_decisions_yml_variant_is_also_pending():
    """Both decisions.yaml and decisions.yml are shared substrate."""
    skills = [_StubSkill("idea-to-pdd")]
    arts = {"idea-to-pdd": [_artifact("decisions.yml")]}
    [step] = _build_steps(skills, arts, {}, "folder-id")
    assert step.step.status == "pending"


def test_step_with_decisions_plus_real_output_is_complete():
    """A real output alongside the substrate file still marks complete."""
    skills = [_StubSkill("idea-to-pdd")]
    arts = {
        "idea-to-pdd": [
            _artifact("decisions.yaml"),
            _artifact("idea-to-pdd.md"),
        ],
    }
    [step] = _build_steps(skills, arts, {}, "folder-id")
    assert step.step.status == "complete"


def test_step_with_no_artifacts_is_pending():
    skills = [_StubSkill("pdd-to-work-order")]
    [step] = _build_steps(skills, {}, {}, "folder-id")
    assert step.step.status == "pending"


# --- run_state.yaml as primary source of truth ---


def test_run_state_done_marks_complete_without_artifacts():
    """The plugin writes literal `done`; we surface `complete`.

    Drive lag means artifact files often arrive after the YAML status
    flip — artifact-presence shouldn't gate the live-run signal.
    """
    skills = [_StubSkill("synthetic-summary", phase="synthetic-data-and-workflows")]
    [step] = _build_steps(
        skills, {}, {}, "folder-id",
        step_status_by_skill={"synthetic-summary": "done"},
    )
    assert step.step.status == "complete"


def test_run_state_complete_marks_complete():
    """`complete` as written by some plugin paths also maps to complete."""
    skills = [_StubSkill("idea-to-pdd")]
    [step] = _build_steps(
        skills, {}, {}, "folder-id",
        step_status_by_skill={"idea-to-pdd": "complete"},
    )
    assert step.step.status == "complete"


def test_run_state_running_surfaces_running():
    """Mid-step running state — invisible to artifact-presence — comes through."""
    skills = [_StubSkill("pdd-to-deliver-app", phase="commcare-setup")]
    [step] = _build_steps(
        skills, {}, {}, "folder-id",
        step_status_by_skill={"pdd-to-deliver-app": "running"},
    )
    assert step.step.status == "running"


def test_run_state_in_progress_normalizes_to_running():
    skills = [_StubSkill("pdd-to-learn-app", phase="commcare-setup")]
    [step] = _build_steps(
        skills, {}, {}, "folder-id",
        step_status_by_skill={"pdd-to-learn-app": "in_progress"},
    )
    assert step.step.status == "running"


def test_run_state_skipped_surfaces_skipped():
    """Smoke-opp no-op steps (e.g. llo-invite with no Preferred LLOs) write
    a skipped/no-op status into run_state.yaml. Artifact-presence would
    flatten that to "pending" forever; we preserve the explicit intent."""
    skills = [_StubSkill("llo-invite", phase="solicitation-management")]
    [step] = _build_steps(
        skills, {}, {}, "folder-id",
        step_status_by_skill={"llo-invite": "skipped"},
    )
    assert step.step.status == "skipped"


def test_run_state_no_op_normalizes_to_skipped():
    skills = [_StubSkill("llo-invite", phase="solicitation-management")]
    [step] = _build_steps(
        skills, {}, {}, "folder-id",
        step_status_by_skill={"llo-invite": "no-op"},
    )
    assert step.step.status == "skipped"


def test_run_state_failed_normalizes_to_error():
    skills = [_StubSkill("ocs-chatbot-eval", phase="ocs-setup")]
    [step] = _build_steps(
        skills, {}, {}, "folder-id",
        step_status_by_skill={"ocs-chatbot-eval": "failed"},
    )
    assert step.step.status == "error"


def test_run_state_pending_stays_pending_even_with_artifacts():
    """If the plugin explicitly says pending (e.g. forked run, artifacts
    carried over but step not yet rerun), trust the plugin over Drive."""
    skills = [_StubSkill("idea-to-pdd")]
    arts = {"idea-to-pdd": [_artifact("idea-to-pdd.md")]}
    [step] = _build_steps(
        skills, arts, {}, "folder-id",
        step_status_by_skill={"idea-to-pdd": "pending"},
    )
    assert step.step.status == "pending"


def test_run_state_missing_falls_back_to_artifact_presence():
    """Step not declared in run_state.yaml — use artifact presence (legacy path)."""
    skills = [_StubSkill("idea-to-pdd")]
    arts = {"idea-to-pdd": [_artifact("idea-to-pdd.md")]}
    [step] = _build_steps(skills, arts, {}, "folder-id", step_status_by_skill={})
    assert step.step.status == "complete"


def test_run_state_unknown_status_falls_back_to_artifact_presence():
    """Unknown status string — defensive fallback rather than crashing."""
    skills = [_StubSkill("idea-to-pdd")]
    arts = {"idea-to-pdd": [_artifact("idea-to-pdd.md")]}
    [step] = _build_steps(
        skills, arts, {}, "folder-id",
        step_status_by_skill={"idea-to-pdd": "weird-new-status-2031"},
    )
    assert step.step.status == "complete"


# --- _extract_step_statuses helper ---


def test_extract_step_statuses_shape_a_steps_dict():
    """Current plugin: `phases: {phase: {status: ..., steps: {skill: {status: ...}}}}`."""
    state = {
        "phases": {
            "commcare-setup": {
                "status": "running",
                "steps": {
                    "pdd-to-learn-app": {"status": "done", "artifacts": {"app_id": "abc"}},
                    "pdd-to-deliver-app": {"status": "running"},
                    "app-deploy": {"status": "pending"},
                },
            },
        },
    }
    out = _extract_step_statuses(state)
    assert out == {
        "pdd-to-learn-app": "done",
        "pdd-to-deliver-app": "running",
        "app-deploy": "pending",
    }


def test_extract_step_statuses_shape_b_bare_strings():
    """Older plugin: `phases: {phase: {skill: status_string}}` (no steps: wrapper)."""
    state = {
        "phases": {
            "idea-to-design": {
                "idea-to-pdd": "done",
                "pdd-to-work-order": "pending",
            },
        },
    }
    out = _extract_step_statuses(state)
    assert out == {
        "idea-to-pdd": "done",
        "pdd-to-work-order": "pending",
    }


def test_extract_step_statuses_skips_phase_level_status_key():
    """In shape A the phase block has a `status:` key alongside `steps:`; it
    shouldn't leak into the skill-status map."""
    state = {
        "phases": {
            "ocs-setup": {
                "status": "complete",  # phase-level
                "steps": {
                    "ocs-agent-setup": {"status": "done"},
                },
            },
        },
    }
    out = _extract_step_statuses(state)
    assert "status" not in out
    assert out == {"ocs-agent-setup": "done"}


def test_extract_step_statuses_handles_missing_phases():
    assert _extract_step_statuses({}) == {}
    assert _extract_step_statuses({"phases": None}) == {}
    assert _extract_step_statuses({"phases": "bogus"}) == {}


def test_extract_step_statuses_handles_malformed_phase_entries():
    """Phase value is a string (malformed) — don't crash."""
    state = {
        "phases": {
            "broken-phase": "complete",  # malformed; should be a dict
            "good-phase": {"steps": {"good-skill": {"status": "done"}}},
        },
    }
    out = _extract_step_statuses(state)
    assert out == {"good-skill": "done"}


# --- Cross-check semantics (artifact-presence + run_state agreement) ---


def test_qa_failed_overrides_run_state_complete():
    """QA-fail verdict wins over a run_state.yaml `done` — surfaces auto-fix loop."""
    from apps.opps.parsers import QAResult
    skills = [_StubSkill("ocs-chatbot-qa", phase="ocs-setup")]
    qa = {
        "ocs-chatbot-qa": QAResult(
            skill="ocs-chatbot-qa", target_skill="ocs-chatbot-qa", verdict="fail",
        ),
    }
    arts = {"ocs-chatbot-qa": [_artifact("ocs-chatbot-qa.md")]}
    [step] = _build_steps(
        skills, arts, {}, "folder-id",
        qa_results_by_skill=qa,
        step_status_by_skill={"ocs-chatbot-qa": "done"},
    )
    assert step.step.status == "qa-failed"
