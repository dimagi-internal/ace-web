"""apps/opps/release_check.py — reading the plugin's release-check verdict."""
from __future__ import annotations

import yaml

from apps.opps.release_check import load_release_check
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient

VERDICT = {
    "schema_version": 1, "kind": "release-check", "workspace": "spark",
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
        "release-check_verdict.yaml": yaml.safe_dump(VERDICT),
        "release-check_report.md": "# report",
    })
    rc = load_release_check(client, kids)
    assert rc["verdict"] == "NOT_READY"
    assert rc["counts"] == {"blockers": 1, "warnings": 1}
    assert rc["blockers"][0]["owner"] == "training-deck-render"
    assert rc["blockers"][0]["fix"] == "re-render"
    assert rc["report"]["file_id"]


def test_a_run_never_checked_has_no_verdict():
    client, kids = _children(**{"run_state.yaml": "phases: {}"})
    assert load_release_check(client, kids) is None


def test_an_unreadable_verdict_is_never_ready():
    client, kids = _children(**{"release-check_verdict.yaml": "verdict: [unclosed"})
    assert load_release_check(client, kids)["verdict"] == "UNREADABLE"
    client, kids = _children(**{"release-check_verdict.yaml": "verdict: SHIP_IT\n"})
    assert load_release_check(client, kids)["verdict"] == "UNREADABLE"


def test_plain_summary_and_action_pass_through_and_are_optional():
    """ACE adds a plain ``summary`` / ``action`` per item (2026-10); older
    verdicts lack them and serve None, so the dialog falls back to
    ``detail`` / ``fix``."""
    verdict = dict(VERDICT)
    verdict["blockers"] = [dict(VERDICT["blockers"][0],
                                summary="The training deck failed its review.",
                                action="Re-render the deck, then re-check.")]
    client, kids = _children(**{"release-check_verdict.yaml": yaml.safe_dump(verdict)})
    rc = load_release_check(client, kids)
    assert rc["blockers"][0]["summary"] == "The training deck failed its review."
    assert rc["blockers"][0]["action"] == "Re-render the deck, then re-check."
    assert rc["warnings"][0]["summary"] is None and rc["warnings"][0]["action"] is None
