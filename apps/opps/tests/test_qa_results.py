"""Tests for QA result serialization (PR #146 / ACE 0.13.88).

QA *parsing* (``_parse_qa_result_yaml`` / ``_load_qa_results`` / the
``_QA_RESULT_PATH_RE`` filename regex) moved into the framework library
(``canopy_runs.drive.parsers``) in the wave-4 run-reader swap and is tested
there. ace-web only keeps the public ``QAResult`` dataclass + its serializer,
so this module pins ``serialize_qa_result`` against a hand-built ``QAResult``.
"""
from __future__ import annotations

from apps.opps.parsers import QAFailure, QAResult
from apps.opps.serializers import serialize_qa_result


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
