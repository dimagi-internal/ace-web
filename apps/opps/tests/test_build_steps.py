"""Pin _build_steps' artifact-presence completeness inference.

The manifest attributes shared-substrate files (decisions.yaml,
decisions.yml) to the first-writer skill (idea-to-pdd) even though many
skills append to them across the lifecycle. After a fork the file is
carried verbatim regardless of whether the producing skill re-ran. So
its presence must NOT be treated as evidence of completion.
"""
from dataclasses import dataclass

from apps.opps.sync import ArtifactRef, _build_steps


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
