"""apps/opps/release_readiness.py — reading the plugin's release-readiness verdict."""
from __future__ import annotations

import yaml

from apps.opps.release_readiness import load_release_readiness
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient

VERDICT = {
    "schema_version": 2, "kind": "release-readiness", "workspace": "spark",
    "opp": "spark-facilitator", "run_id": "r1", "checked_at": "2026-10-01T20:00:00Z",
    "run_last_write": "2026-10-01T19:00:00Z", "verdict": "NOT_READY", "read_only": False,
    "counts": {"blockers": 1, "warnings": 1},
    "blockers": [{"id": "deck", "area": "eval", "severity": "blocker",
                  "owner": "training-deck-render", "detail": "4.66 fail", "fix": "re-render"}],
    "warnings": [{"id": "flags", "area": "connect", "severity": "warning",
                  "owner": "connect-opp-setup", "detail": "ace#2419", "fix": "known"}],
}


def _children(**files):
    client = FakeDriveClient.from_tree({"run": files})
    return client, client.list_folder(client.folder_id("run"))


def test_reads_the_verdict_and_links_the_report():
    client, kids = _children(**{
        "release-readiness_verdict.yaml": yaml.safe_dump(VERDICT),
        "release-readiness_report.md": "# report",
    })
    rc = load_release_readiness(client, kids)
    assert rc["verdict"] == "NOT_READY"
    assert rc["counts"] == {"blockers": 1, "warnings": 1}
    assert rc["blockers"][0]["owner"] == "training-deck-render"
    assert rc["blockers"][0]["fix"] == "re-render"
    assert rc["report"]["file_id"]


def test_a_run_never_checked_has_no_verdict():
    client, kids = _children(**{"run_state.yaml": "phases: {}"})
    assert load_release_readiness(client, kids) is None


def test_an_unreadable_verdict_is_never_ready():
    client, kids = _children(**{"release-readiness_verdict.yaml": "verdict: [unclosed"})
    assert load_release_readiness(client, kids)["verdict"] == "UNREADABLE"
    client, kids = _children(**{"release-readiness_verdict.yaml": "verdict: SHIP_IT\n"})
    assert load_release_readiness(client, kids)["verdict"] == "UNREADABLE"


def test_plain_summary_and_action_pass_through_and_are_optional():
    """ACE adds a plain ``summary`` / ``action`` per item (2026-10); older
    verdicts lack them and serve None, so the dialog falls back to
    ``detail`` / ``fix``."""
    verdict = dict(VERDICT)
    verdict["blockers"] = [dict(VERDICT["blockers"][0],
                                summary="The training deck failed its review.",
                                action="Re-render the deck, then re-check.")]
    client, kids = _children(**{"release-readiness_verdict.yaml": yaml.safe_dump(verdict)})
    rc = load_release_readiness(client, kids)
    assert rc["blockers"][0]["summary"] == "The training deck failed its review."
    assert rc["blockers"][0]["action"] == "Re-render the deck, then re-check."
    assert rc["warnings"][0]["summary"] is None and rc["warnings"][0]["action"] is None


def test_merged_is_the_list_of_folded_finding_ids():
    verdict = dict(VERDICT)
    verdict["blockers"] = [dict(VERDICT["blockers"][0], merged=["deck-2", "deck-3", {"x": 1}])]
    verdict["warnings"] = [dict(VERDICT["warnings"][0], merged=True)]
    client, kids = _children(**{"release-readiness_verdict.yaml": yaml.safe_dump(verdict)})
    rc = load_release_readiness(client, kids)
    assert rc["blockers"][0]["merged"] == ["deck-2", "deck-3"]
    assert rc["warnings"][0]["merged"] == []
    assert rc["blockers"][0]["severity"] == "blocker"


PLAN = {
    "schema_version": 1, "workspace": "spark", "opp": "spark-facilitator", "run_id": "r1",
    "reviewers": [{"email": "a@x.org", "role": "viewer"}],
    "options": {"forward_source": True, "allow_cross_workspace_forward": True,
                "allow_shared_connect": False, "unknown": True},
    "actions": [
        {"step": 1, "id": "hq:a@x.org", "system": "hq", "kind": "hq_invite",
         "email": "a@x.org", "target": "spark-hq", "role": "App Editor"},
        {"step": 2, "id": "connect:a@x.org:org", "system": "connect",
         "kind": "connect_org_member", "email": "a@x.org", "target": "org", "role": "viewer",
         "shared": False},
        {"step": 3, "id": "drive:f1", "system": "drive", "kind": "drive_share", "target": "f1",
         "title": "PDD", "url": "https://docs.google.com/document/d/f1", "role": "commenter",
         "scope": "anyone_with_link"},
        {"step": 4, "id": "forward-source", "system": "ace-web", "kind": "forward_source",
         "target": "dimagi-team/spark-facilitator/r0", "cross_workspace": True},
        {"step": 5, "id": "ace-web:a@x.org", "system": "ace-web", "kind": "ace_web_invite",
         "email": "a@x.org", "target": "spark", "role": "viewer", "secret": {"nested": 1}},
        {"step": 6, "id": "email:a@x.org", "system": "email", "kind": "email",
         "email": "a@x.org", "target": "a@x.org", "subject": "Review"},
        "not-a-dict",
        {"step": 7, "id": "no-kind"},
    ],
    "not_granted": [
        {"email": "a@x.org", "system": "ocs", "reason": "public chat link, no account"}],
    "emails": [{"to": "a@x.org", "subject": "Review",
                "body": "Hi\n\n  {{ACCEPT_LINK}}\n" + "x" * 20_000}],
}

READY_V2 = dict(
    VERDICT, schema_version=2, kind="release-readiness", verdict="READY",
    counts={"blockers": 0, "warnings": 0}, blockers=[], warnings=[],
    reviewers=[{"email": "a@x.org", "role": "viewer"}, {"role": "no-email"}],
    run_state_hash="sha256:aa", plan_hash="sha256:bb", release_plan=PLAN,
)


def test_only_the_release_readiness_files_are_read():
    """The retired file names are not a fallback: a run carrying only them has
    not been validated, and a report is never borrowed from them."""
    legacy_verdict, legacy_report = "release-check_verdict.yaml", "release-check_report.md"
    client, kids = _children(**{
        legacy_verdict: yaml.safe_dump(dict(VERDICT, verdict="READY")),
        legacy_report: "# old",
    })
    assert load_release_readiness(client, kids) is None
    client, kids = _children(**{
        legacy_report: "# old",
        "release-readiness_verdict.yaml": yaml.safe_dump(READY_V2),
    })
    rc = load_release_readiness(client, kids)
    assert rc["kind"] == "release-readiness" and rc["verdict"] == "READY"
    assert rc["report"] is None


def test_the_release_plan_is_sanitized():
    client, kids = _children(**{"release-readiness_verdict.yaml": yaml.safe_dump(READY_V2)})
    rc = load_release_readiness(client, kids)
    assert rc["reviewers"] == [{"email": "a@x.org", "role": "viewer"}]
    plan = rc["release_plan"]
    assert plan["reviewers"] == [{"email": "a@x.org", "role": "viewer"}]
    # The non-dict and the kind-less action are dropped; order is kept.
    assert [a["kind"] for a in plan["actions"]] == [
        "hq_invite", "connect_org_member", "drive_share", "forward_source",
        "ace_web_invite", "email",
    ]
    hq, connect, drive, fwd, invite, _ = plan["actions"]
    assert hq["step"] == 1 and hq["role"] == "App Editor"
    assert connect["shared"] is False
    assert drive["scope"] == "anyone_with_link" and drive["title"] == "PDD"
    assert fwd["cross_workspace"] is True and "shared" not in fwd
    assert "secret" not in invite
    assert plan["options"] == {"forward_source": True, "allow_cross_workspace_forward": True,
                               "allow_shared_connect": False}
    assert plan["not_granted"] == [
        {"email": "a@x.org", "system": "ocs", "reason": "public chat link, no account"}]
    body = plan["emails"][0]["body"]
    assert body.startswith("Hi\n\n  {{ACCEPT_LINK}}\n") and len(body) == 10_000


def test_a_ready_verdict_without_a_plan_has_no_plan():
    no_plan = {k: v for k, v in READY_V2.items() if k != "release_plan"}
    client, kids = _children(**{"release-readiness_verdict.yaml": yaml.safe_dump(no_plan)})
    rc = load_release_readiness(client, kids)
    assert rc["verdict"] == "READY" and rc["release_plan"] is None


def test_a_not_ready_verdict_never_serves_a_plan_and_bad_plans_degrade():
    client, kids = _children(**{"release-readiness_verdict.yaml": yaml.safe_dump(
        dict(READY_V2, verdict="NOT_READY"))})
    assert load_release_readiness(client, kids)["release_plan"] is None
    empty = {"reviewers": [], "options": {}, "actions": [], "not_granted": [], "emails": []}
    for bad in ("a string", [1, 2], {"actions": "nope", "emails": {"to": "x"}}):
        client, kids = _children(**{"release-readiness_verdict.yaml": yaml.safe_dump(
            dict(READY_V2, release_plan=bad, reviewers="nope", counts="nope"))})
        rc = load_release_readiness(client, kids)
        assert rc["verdict"] == "READY" and rc["reviewers"] == []
        assert rc["counts"] == {"blockers": 0, "warnings": 0}
        assert rc["release_plan"] in (None, empty)
