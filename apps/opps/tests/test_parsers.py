"""Tests for the Drive file parsers."""
import pytest

from apps.opps.parsers import (
    OppManifest,
    RunManifest,
    StepManifest,
    parse_events_jsonl,
    parse_gates_jsonl,
    parse_judge_yaml,
    parse_opp_yaml,
    parse_run_yaml,
    parse_step_yaml,
)


def test_parse_opp_yaml_full():
    body = """
slug: malaria-pilot
display_name: Malaria Pilot — Northern Mozambique
created_at: 2026-03-15T09:00:00Z
created_by: neal@dimagi.com
labels:
  - malaria
  - mozambique
  - q2-2026
current_run_id: 2026-04-06-002
"""
    opp: OppManifest = parse_opp_yaml(body)
    assert opp.slug == "malaria-pilot"
    assert opp.display_name == "Malaria Pilot — Northern Mozambique"
    assert opp.labels == ["malaria", "mozambique", "q2-2026"]
    assert opp.current_run_id == "2026-04-06-002"
    assert opp.created_by == "neal@dimagi.com"


def test_parse_opp_yaml_minimal():
    body = "slug: test\ndisplay_name: Test\n"
    opp = parse_opp_yaml(body)
    assert opp.slug == "test"
    assert opp.labels == []
    assert opp.current_run_id is None


def test_parse_opp_yaml_missing_slug_raises():
    with pytest.raises(ValueError, match="slug"):
        parse_opp_yaml("display_name: x\n")


def test_parse_run_yaml_full():
    body = """
run_id: 2026-04-06-002
mode: review
status: running
started_at: 2026-04-06T10:12:00Z
completed_at: null
current_phase: app-building
current_step: app-deploy
skill_versions:
  idea-to-idd: 4f2b8c1
  app-deploy: 8a91f22
notes: |
  Re-run after editing app-deploy SKILL.md.
"""
    run: RunManifest = parse_run_yaml(body)
    assert run.run_id == "2026-04-06-002"
    assert run.mode == "review"
    assert run.status == "running"
    assert run.current_step == "app-deploy"
    assert run.skill_versions["app-deploy"] == "8a91f22"
    assert run.completed_at is None


def test_parse_run_yaml_rejects_bad_mode():
    body = "run_id: r1\nmode: banana\nstatus: running\n"
    with pytest.raises(ValueError, match="mode"):
        parse_run_yaml(body)


def test_parse_run_yaml_rejects_bad_status():
    body = "run_id: r1\nmode: review\nstatus: wat\n"
    with pytest.raises(ValueError, match="status"):
        parse_run_yaml(body)


def test_parse_step_yaml():
    body = """
skill_name: app-deploy
phase: app-building
ordinal: 4
status: gate-pending
started_at: 2026-04-06T10:34:00Z
completed_at: null
error: null
preview_stats:
  apps_packaged: 2
  target_domain: crispr-connect
"""
    step: StepManifest = parse_step_yaml(body)
    assert step.skill_name == "app-deploy"
    assert step.status == "gate-pending"
    assert step.preview_stats["apps_packaged"] == 2


def test_parse_judge_yaml():
    body = """
score: 9.2
passed: true
evaluated_at: 2026-04-06T10:14:25Z
criteria:
  completeness: 9.5
  specificity: 9.0
rationale: |
  The IDD is comprehensive.
"""
    judge = parse_judge_yaml(body)
    assert judge.score == 9.2
    assert judge.passed is True
    assert judge.criteria["completeness"] == 9.5
    assert "comprehensive" in judge.rationale


def test_parse_gates_jsonl():
    line1 = '{"ts":"2026-04-01T10:00:00Z","decision":"approved",'
    line1 += '"decided_by":"neal@dimagi.com","note":"lgtm"}'
    line2 = '{"ts":"2026-04-06T10:14:25Z","decision":"pending",'
    line2 += '"payload":{"reason":"awaiting review"}}'
    body = line1 + "\n" + line2 + "\n"
    gates = parse_gates_jsonl(body)
    assert len(gates) == 2
    assert gates[0].decision == "approved"
    assert gates[0].decided_by == "neal@dimagi.com"
    assert gates[1].decision == "pending"
    assert gates[1].decided_by == ""


def test_parse_gates_jsonl_empty():
    assert parse_gates_jsonl("") == []
    assert parse_gates_jsonl("\n\n") == []


def test_parse_gates_jsonl_malformed_line_is_skipped():
    body = """{"ts":"2026-04-01T10:00:00Z","decision":"approved"}
not-json
{"ts":"2026-04-02T10:00:00Z","decision":"rejected"}
"""
    gates = parse_gates_jsonl(body)
    assert len(gates) == 2
    assert [g.decision for g in gates] == ["approved", "rejected"]


def test_parse_events_jsonl():
    body = """{"ts":"2026-04-06T10:12:00Z","kind":"run.started","payload":{"mode":"review"}}
{"ts":"2026-04-06T10:12:03Z","kind":"step.started","step":"idea-to-idd"}
"""
    events = parse_events_jsonl(body)
    assert len(events) == 2
    assert events[0].kind == "run.started"
    assert events[1].step == "idea-to-idd"
