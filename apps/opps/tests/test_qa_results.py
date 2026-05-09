"""Tests for QA result parsing and serialization (PR #146 / ACE 0.13.88).

Covers:
- ``_parse_qa_result_yaml``: YAML body → ``QAResult``
- ``_load_qa_results``: Drive file walk → {target_skill: QAResult}
- ``_QA_RESULT_PATH_RE``: filename regex
- ``serialize_qa_result``: API serialization
- StepSnapshot.status reflects QA-failed when QA verdict is fail
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.opps.drive_client import DriveFile, FileContent
from apps.opps.parsers import QAFailure, QAResult
from apps.opps.serializers import serialize_qa_result
from apps.opps.sync import (
    _QA_RESULT_PATH_RE,
    _build_steps,
    _load_qa_results,
    _parse_qa_result_yaml,
)

PASS_YAML = """
skill: idea-to-pdd-qa
target: turmeric
ran_at: 2026-05-08T19:00:00Z
capture_path: 1-design/idea-to-pdd.md
verdict: pass
stats:
  checks_run: 6
  checks_passed: 6
  checks_failed: 0
failures: []
"""


FAIL_YAML = """
skill: idea-to-pdd-qa
target: turmeric
ran_at: 2026-05-08T19:01:00Z
capture_path: 1-design/idea-to-pdd.md
verdict: fail
stats:
  checks_run: 6
  checks_passed: 4
  checks_failed: 2
failures:
  - check: all_required_sections_present
    type: static
    severity: blocker
    detail: "missing § Target Population"
    auto_fix_hint: "regenerate with explicit instruction to add Target Population"
  - check: stress_test_appendix_present
    type: static
    severity: blocker
    detail: "missing § Stress Test Results appendix"
    auto_fix_hint: "add a Stress Test Results section"
auto_fix:
  attempted: true
  attempts: 1
  succeeded: false
"""


# ── Path regex ─────────────────────────────────────────────────────


class TestQAResultPathRegex:
    def test_matches_idea_to_pdd_qa_result(self):
        m = _QA_RESULT_PATH_RE.match("1-design/idea-to-pdd-qa_result.yaml")
        assert m is not None
        assert m.group("qa_skill") == "idea-to-pdd-qa"

    def test_matches_other_phase_folders(self):
        m = _QA_RESULT_PATH_RE.match("2-commcare/pdd-to-learn-app-qa_result.yaml")
        assert m is not None
        assert m.group("qa_skill") == "pdd-to-learn-app-qa"

    def test_tolerates_yml_extension(self):
        m = _QA_RESULT_PATH_RE.match("1-design/idea-to-pdd-qa_result.yml")
        assert m is not None

    def test_does_not_match_eval_verdict(self):
        assert _QA_RESULT_PATH_RE.match("1-design/idea-to-pdd-eval_verdict.yaml") is None
        assert _QA_RESULT_PATH_RE.match("1-design/idea-to-pdd_verdict.yaml") is None

    def test_does_not_match_root_level(self):
        # Must be inside a phase folder.
        assert _QA_RESULT_PATH_RE.match("idea-to-pdd-qa_result.yaml") is None


# ── YAML parsing ───────────────────────────────────────────────────


class TestParseQAResultYaml:
    def test_parses_pass_result(self):
        r = _parse_qa_result_yaml(PASS_YAML, qa_skill="idea-to-pdd-qa")
        assert r is not None
        assert r.skill == "idea-to-pdd-qa"
        assert r.target_skill == "idea-to-pdd"
        assert r.verdict == "pass"
        assert r.checks_run == 6
        assert r.checks_passed == 6
        assert r.checks_failed == 0
        assert r.failures == []

    def test_parses_fail_result_with_failures(self):
        r = _parse_qa_result_yaml(FAIL_YAML, qa_skill="idea-to-pdd-qa")
        assert r is not None
        assert r.verdict == "fail"
        assert len(r.failures) == 2
        first = r.failures[0]
        assert first.check == "all_required_sections_present"
        assert first.detail == "missing § Target Population"
        assert "Target Population" in first.auto_fix_hint
        assert first.type == "static"

    def test_parses_auto_fix_metadata(self):
        r = _parse_qa_result_yaml(FAIL_YAML, qa_skill="idea-to-pdd-qa")
        assert r is not None
        assert r.auto_fix_attempted is True
        assert r.auto_fix_attempts == 1
        assert r.auto_fix_succeeded is False

    def test_target_skill_strips_qa_suffix(self):
        r = _parse_qa_result_yaml(PASS_YAML, qa_skill="pdd-to-learn-app-qa")
        assert r is not None
        assert r.target_skill == "pdd-to-learn-app"

    def test_returns_none_on_missing_verdict(self):
        body = "skill: idea-to-pdd-qa\nstats:\n  checks_run: 0\n"
        assert _parse_qa_result_yaml(body, qa_skill="idea-to-pdd-qa") is None

    def test_returns_none_on_unknown_verdict_tier(self):
        body = "skill: idea-to-pdd-qa\nverdict: warn\nstats:\n  checks_run: 0\n"
        assert _parse_qa_result_yaml(body, qa_skill="idea-to-pdd-qa") is None

    def test_returns_none_on_invalid_yaml(self):
        assert _parse_qa_result_yaml("not: [valid: yaml: at all", qa_skill="idea-to-pdd-qa") is None

    def test_handles_incomplete_verdict(self):
        body = (
            "skill: idea-to-pdd-qa\n"
            "verdict: incomplete\n"
            "stats:\n"
            "  checks_run: 0\n"
            "  checks_passed: 0\n"
            "  checks_failed: 0\n"
            "failures: []\n"
        )
        r = _parse_qa_result_yaml(body, qa_skill="idea-to-pdd-qa")
        assert r is not None
        assert r.verdict == "incomplete"


# ── _load_qa_results (file walker) ─────────────────────────────────


class _Client:
    """Stub DriveClient that returns canned YAML by file id."""

    def __init__(self, contents: dict[str, str]):
        self.contents = contents

    def get_content(self, file_id: str, mime_type: str):
        return FileContent(content=self.contents[file_id], content_type=mime_type)


def _file(*, id: str, name: str, path: str, mime_type: str = "text/yaml") -> DriveFile:
    return DriveFile(
        id=id,
        name=name,
        mime_type=mime_type,
        web_view_link="",
        path=path,
    )


class TestLoadQAResults:
    def test_walks_qa_result_files(self):
        files = [
            _file(
                id="f1",
                name="idea-to-pdd-qa_result.yaml",
                path="1-design/idea-to-pdd-qa_result.yaml",
            ),
            # not a QA file
            _file(id="f2", name="idea-to-pdd.md", path="1-design/idea-to-pdd.md"),
            # eval, not QA
            _file(
                id="f3",
                name="idea-to-pdd-eval_verdict.yaml",
                path="1-design/idea-to-pdd-eval_verdict.yaml",
            ),
        ]
        client = _Client({"f1": PASS_YAML})
        results = _load_qa_results(client, files)
        assert "idea-to-pdd" in results
        assert results["idea-to-pdd"].verdict == "pass"
        assert len(results) == 1

    def test_keeps_latest_when_multiple_runs(self):
        # Two QA results for the same target — latest ran_at wins.
        later = (
            PASS_YAML
            .replace("19:00:00Z", "20:00:00Z")
            .replace("verdict: pass", "verdict: fail")
            .replace("checks_failed: 0", "checks_failed: 1")
        )
        # Make later valid by adding a failure entry.
        later = later.replace(
            "failures: []",
            (
                "failures:\n"
                "  - check: x\n"
                "    type: static\n"
                "    severity: blocker\n"
                "    detail: bad\n"
                "    auto_fix_hint: fix\n"
            ),
        )
        files = [
            _file(id="early", name="x.yaml", path="1-design/idea-to-pdd-qa_result.yaml"),
        ]
        # Same path — simulate replacement by varying file id sequentially.
        files = [
            _file(id="early", name="x.yaml", path="1-design/idea-to-pdd-qa_result.yaml"),
            _file(id="late", name="x.yaml", path="1-design/idea-to-pdd-qa_result.yaml"),
        ]
        client = _Client({"early": PASS_YAML, "late": later})
        results = _load_qa_results(client, files)
        # The latest ran_at should win.
        assert results["idea-to-pdd"].verdict == "fail"

    def test_empty_files_yields_empty_dict(self):
        client = _Client({})
        results = _load_qa_results(client, [])
        assert results == {}

    def test_skips_unparseable_yaml(self):
        files = [
            _file(id="bad", name="x.yaml", path="1-design/idea-to-pdd-qa_result.yaml"),
        ]
        client = _Client({"bad": "not-valid-yaml: [["})
        results = _load_qa_results(client, files)
        assert results == {}


# ── Serialization ──────────────────────────────────────────────────


class TestSerializeQAResult:
    def test_serializes_pass(self):
        r = QAResult(
            skill="idea-to-pdd-qa",
            target_skill="idea-to-pdd",
            verdict="pass",
            ran_at="2026-05-08T19:00:00Z",
            capture_path="1-design/idea-to-pdd.md",
            checks_run=6,
            checks_passed=6,
            checks_failed=0,
            failures=[],
        )
        out = serialize_qa_result(r)
        assert out is not None
        assert out["verdict"] == "pass"
        assert out["target_skill"] == "idea-to-pdd"
        assert out["stats"]["checks_passed"] == 6
        assert out["failures"] == []
        assert out["auto_fix"] is None  # auto_fix_attempted is None

    def test_serializes_fail_with_failures(self):
        r = QAResult(
            skill="idea-to-pdd-qa",
            target_skill="idea-to-pdd",
            verdict="fail",
            ran_at="2026-05-08T19:01:00Z",
            capture_path="1-design/idea-to-pdd.md",
            checks_run=6,
            checks_passed=4,
            checks_failed=2,
            failures=[
                QAFailure(
                    check="all_required_sections_present",
                    type="static",
                    detail="missing § Target Population",
                    auto_fix_hint="add the section",
                ),
            ],
            auto_fix_attempted=True,
            auto_fix_attempts=2,
            auto_fix_succeeded=False,
        )
        out = serialize_qa_result(r)
        assert out is not None
        assert out["verdict"] == "fail"
        assert len(out["failures"]) == 1
        assert out["failures"][0]["check"] == "all_required_sections_present"
        assert out["failures"][0]["auto_fix_hint"] == "add the section"
        assert out["auto_fix"]["attempted"] is True
        assert out["auto_fix"]["attempts"] == 2
        assert out["auto_fix"]["succeeded"] is False

    def test_serializes_none(self):
        assert serialize_qa_result(None) is None


# ── _build_steps integration ───────────────────────────────────────


@dataclass
class _StubSkillMeta:
    name: str
    phase: str = "design"
    ordinal: int = 1


class TestBuildStepsQAStatus:
    def test_qa_failed_status_when_qa_fails(self):
        skill_registry = [_StubSkillMeta(name="idea-to-pdd")]
        qa_results = {
            "idea-to-pdd": QAResult(
                skill="idea-to-pdd-qa",
                target_skill="idea-to-pdd",
                verdict="fail",
                ran_at="2026-05-08T19:00:00Z",
                checks_run=6,
                checks_passed=4,
                checks_failed=2,
                failures=[
                    QAFailure(
                        check="x", type="static", detail="d", auto_fix_hint="h"
                    )
                ],
            )
        }
        steps = _build_steps(
            skill_registry,
            artifacts_by_skill={"idea-to-pdd": []},
            verdicts_by_skill={},
            folder_id="folder",
            qa_results_by_skill=qa_results,
        )
        assert len(steps) == 1
        assert steps[0].step.status == "qa-failed"
        assert steps[0].qa_result is not None
        assert steps[0].qa_result.verdict == "fail"

    def test_qa_pass_does_not_change_status(self):
        skill_registry = [_StubSkillMeta(name="idea-to-pdd")]
        qa_results = {
            "idea-to-pdd": QAResult(
                skill="idea-to-pdd-qa",
                target_skill="idea-to-pdd",
                verdict="pass",
                checks_run=6,
                checks_passed=6,
                checks_failed=0,
                failures=[],
            )
        }
        steps = _build_steps(
            skill_registry,
            artifacts_by_skill={"idea-to-pdd": [object()]},  # has artifacts
            verdicts_by_skill={},
            folder_id="folder",
            qa_results_by_skill=qa_results,
        )
        assert steps[0].step.status == "complete"
        assert steps[0].qa_result is not None
        assert steps[0].qa_result.verdict == "pass"

    def test_no_qa_result_falls_back_to_default_status(self):
        skill_registry = [_StubSkillMeta(name="idea-to-pdd")]
        steps = _build_steps(
            skill_registry,
            artifacts_by_skill={"idea-to-pdd": []},
            verdicts_by_skill={},
            folder_id="folder",
        )
        assert steps[0].step.status == "pending"
        assert steps[0].qa_result is None
