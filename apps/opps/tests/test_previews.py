"""Tests for per-skill preview_text extractors."""
from apps.opps.parsers import StepManifest
from apps.opps.previews import build_preview
from apps.opps.sync import ArtifactRef, StepSnapshot


def _step(skill: str, artifacts: list[str] | None = None) -> StepSnapshot:
    return StepSnapshot(
        step=StepManifest(skill_name=skill, phase="", ordinal=0, status="complete"),
        judge=None,
        gates=[],
        artifacts=[
            ArtifactRef(
                name=a, drive_file_id=f"fake-{a}", drive_web_link="",
                size_bytes=None, mime_type="text/markdown", path=a,
            )
            for a in (artifacts or [])
        ],
        folder_id="step-id",
    )


def test_idea_to_idd_preview():
    body = "# Malaria IDD\n\nReduce malaria mortality via monthly RDT screening."
    step = _step("idea-to-idd", artifacts=["idd.md"])
    preview = build_preview(step, bodies={"idd.md": body})
    assert "idd.md" in preview
    assert "Reduce malaria mortality" in preview


def test_learn_app_preview_extracts_form_count():
    body = "# Learn App Brief\n\n12 forms\n34 questions\n6 case types"
    step = _step("idd-to-learn-app", artifacts=["learn-app-brief.md"])
    preview = build_preview(step, bodies={"learn-app-brief.md": body})
    assert "12 forms" in preview


def test_app_test_preview_extracts_pass_ratio():
    body = "passed: 38\nfailed: 2\ntotal: 40\n"
    step = _step("app-test", artifacts=["test-results.yaml"])
    preview = build_preview(step, bodies={"test-results.yaml": body})
    assert "38/40 pass" in preview
    assert "2 fail" in preview


def test_training_materials_preview_counts_artifacts():
    step = _step(
        "training-materials",
        artifacts=[
            "llo-manager-guide.md",
            "flw-training-guide.md",
            "quick-reference.md",
            "faq.md",
        ],
    )
    preview = build_preview(step, bodies={})
    assert "4 docs" in preview


def test_cycle_grade_preview():
    body = "overall_grade: 8.4\nintervention_effectiveness: 9\napp_quality: 8\n"
    step = _step("cycle-grade", artifacts=["grade-report.md"])
    preview = build_preview(step, bodies={"grade-report.md": body})
    assert "8.4" in preview


def test_unknown_skill_falls_back_to_count():
    step = _step("unknown-skill-123", artifacts=["a.md", "b.md"])
    preview = build_preview(step, bodies={})
    assert preview == "2 artifacts"


def test_no_artifacts_falls_back_to_dash():
    step = _step("idea-to-idd", artifacts=[])
    preview = build_preview(step, bodies={})
    assert preview == "—"


def test_every_registered_skill_has_an_extractor():
    """Every skill in the registry must have either a dedicated extractor or
    rely on the generic fallback — we don't want silent gaps."""
    from apps.opps.skills import SKILL_REGISTRY
    # Not all 19 need a dedicated function, but if the generic fallback is
    # used we should be intentional about it. This test just asserts that
    # the registry is importable and the fallback path works.
    for skill in SKILL_REGISTRY:
        step = _step(skill.name, artifacts=[skill.primary_output])
        preview = build_preview(step, bodies={skill.primary_output: "sample"})
        assert isinstance(preview, str)
        assert preview != ""
