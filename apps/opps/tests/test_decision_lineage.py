"""Decision lineage — how a run's decisions evolved across earlier runs.

Fixtures are the REAL spark-facilitator runs, trimmed to the rows these
tests follow (``fixtures/lineage/``, rows verbatim):

    spark/20261001-2208          clone of ↓
    dimagi-team/20261001-2208    forked from ↓ at commcare-setup (seeded)
    dimagi-team/20260926-1800    forked from ↓ at synthetic-data-and-workflows
    dimagi-team/20260925-1536    the root
    dimagi-team/20260926-1413    an independent run of the same opp (not in the chain)

The cases they pin are the ones that actually occur: a value carried
unchanged across four runs (``working-language``), one re-written under a
new id at every hop (``connect-latitude-payment-amount`` → ``…-2208`` →
``…-spark``), one renamed by a fork (``learn-latitude-baseline-pretest`` →
``learn-latitude-starting-quiz``), a human override, a changed value, and a
row new in the clone with no earlier match.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from django.contrib.auth import get_user_model

from apps.opps.decision_lineage import (
    ChainRun,
    build_lineage,
    load_chain,
    parent_of,
    run_date,
    shape_for_viewer,
)
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.workspaces.models import RunClone, Workspace, WorkspaceMembership

FIX = Path(__file__).parent / "fixtures" / "lineage"
OPP = "spark-facilitator"
RUN = "20261001-2208"

User = get_user_model()


def _text(ws: str, run: str, name: str) -> str:
    return (FIX / f"{ws}__{run}__{name}").read_text()


def _rows(ws: str, run: str) -> list[dict]:
    return yaml.safe_load(_text(ws, run, "decisions.yaml"))["decisions"]


def _run(ws: str, run: str, via: str = "", at: str = "") -> ChainRun:
    state = yaml.safe_load(_text(ws, run, "run_state.yaml"))
    return ChainRun(ws, OPP, run, via, at, run_date(run, state), _rows(ws, run))


def _spark_chain() -> list[ChainRun]:
    return [
        _run("spark", RUN, "cloned"),
        _run("dimagi-team", RUN, "seeded", "commcare-setup"),
        _run("dimagi-team", "20260926-1800", "forked", "synthetic-data-and-workflows"),
        _run("dimagi-team", "20260925-1536"),
    ]


# ─── Origins ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def spark_core() -> dict:
    return build_lineage(_spark_chain())


def test_a_value_unchanged_since_the_root_is_carried_from_the_root(spark_core):
    o = spark_core["origins"]["working-language"]
    assert o["kind"] == "carried"
    # The badge names where the value was first set, not just the parent.
    assert o["from_run"] == "20260925-1536"


def test_a_value_rewritten_under_a_new_id_is_reaffirmed_not_new(spark_core):
    """`connect-latitude-payment-amount` became `…-2208` then `…-spark`: same
    7500 at every hop. The seeded fork re-ran Connect setup in dimagi-team and
    re-emitted it — that is the re-decision; the clone's `-spark` copy is not."""
    o = spark_core["origins"]["connect-latitude-payment-amount-spark"]
    assert o["kind"] == "reaffirmed"
    assert o["from_run"] == "20260925-1536"
    assert (o["in_workspace"], o["in_run"]) == ("dimagi-team", RUN)


def test_a_human_override_says_a_person_set_it(spark_core):
    o = spark_core["origins"]["sol-devices-and-system-of-record-2208"]
    assert o["kind"] == "human"
    assert o["status"] == "overridden"


def test_a_value_that_differs_from_the_parent_is_changed_here(spark_core):
    o = spark_core["origins"]["program-reuse-vs-create-spark"]
    assert o["kind"] == "changed"
    assert o["from_run"] == RUN
    assert o["from_workspace"] == "dimagi-team"
    assert o["previous_value"]
    # The copy into spark is what changed it (the partner's own program).
    assert o["on_copy"] is True
    assert (o["in_workspace"], o["in_run"]) == ("spark", RUN)


def test_a_row_no_earlier_run_has_is_new(spark_core):
    rid = "open-question-recording-path-whole-community-group-declines"
    assert spark_core["origins"][rid]["kind"] == "new"
    hist = spark_core["histories"][rid]
    # Honest: every earlier run says "not found", nothing is guessed.
    assert [e["found"] for e in hist] == [False, False, False, True]


def test_superseded_rows_get_no_origin(spark_core):
    assert "connect-latitude-payment-amount-2208" not in spark_core["origins"]
    assert "learn-latitude-baseline-pretest" not in spark_core["origins"]


def test_counts_add_up_to_the_live_rows(spark_core):
    live = [r for r in _rows("spark", RUN) if not r.get("superseded_by")]
    assert sum(spark_core["counts"].values()) == len(live)


# ─── Histories ──────────────────────────────────────────────────────


def test_history_runs_oldest_first_and_follows_renamed_ids(spark_core):
    hist = spark_core["histories"]["connect-latitude-payment-amount-spark"]
    # The clone and its source are ONE run: one entry, the source's, marked
    # as copied to spark and as this run.
    assert [(e["workspace"], e["run_id"]) for e in hist] == [
        ("dimagi-team", "20260925-1536"),
        ("dimagi-team", "20260926-1800"),
        ("dimagi-team", RUN),
    ]
    assert [e["row_id"] for e in hist] == [
        "connect-latitude-payment-amount",
        "connect-latitude-payment-amount",
        "connect-latitude-payment-amount-2208",
    ]
    assert {e["value"] for e in hist} == {"7500"}
    assert hist[-1]["current"] is True
    assert [c["workspace"] for c in hist[-1]["copied_to"]] == ["spark"]


def test_history_shows_a_fork_renaming_a_decision(spark_core):
    hist = spark_core["histories"]["learn-latitude-starting-quiz"]
    by_run = {(e["workspace"], e["run_id"]): e for e in hist}
    old = by_run[("dimagi-team", "20260926-1800")]
    assert old["row_id"] == "learn-latitude-baseline-pretest"
    assert old["match"] == "earlier-id"
    assert old["value"] != by_run[("dimagi-team", RUN)]["value"]
    # The seeded fork is where it changed — the clone only copied that.
    o = spark_core["origins"]["learn-latitude-starting-quiz"]
    assert (o["kind"], o["in_workspace"], o["from_run"]) == (
        "changed", "dimagi-team", "20260926-1800",
    )


def test_history_carries_the_humans_reason_on_an_override(spark_core):
    last = spark_core["histories"]["sol-devices-and-system-of-record-2208"][-1]
    assert last["status"] == "overridden"
    assert last["value"] == "Ask about devices; devices costed separately"
    assert last["reason"].startswith("Operator decision 2026-10-04")
    # The display value describes the AI default — it must not mask a human answer.
    assert last["plain_value"] == ""


def test_retired_id_shape_is_matched_when_nothing_else_links_it():
    """A fork retires `<id>` as `<id>-<source-run>`; with no supersession
    chain linking it (an older log), the suffix alone still finds it."""
    parent = ChainRun("ws", OPP, "20260101-0900", rows=[
        {"id": "rate", "ai-default": "5", "status": "ai-default"},
    ], date="2026-01-01")
    child = ChainRun("ws", OPP, "20260102-0900", via="forked", rows=[
        {"id": "rate-20260101-0900", "ai-default": "5"},
    ], date="2026-01-02")
    head = ChainRun("ws", OPP, "20260103-0900", via="forked", rows=[
        {"id": "rate-20260101-0900", "ai-default": "6"},
    ], date="2026-01-03")
    core = build_lineage([head, child, parent])
    hist = core["histories"]["rate-20260101-0900"]
    assert hist[0]["match"] == "retired-id" and hist[0]["row_id"] == "rate"
    assert core["origins"]["rate-20260101-0900"]["kind"] == "changed"


def test_scope_opp_adds_runs_outside_the_chain():
    chain = _spark_chain()
    other = _run("dimagi-team", "20260926-1413")
    other.in_lineage = False
    core = build_lineage(chain, [other])
    hist = core["histories"]["working-language"]
    outside = [e for e in hist if not e["in_lineage"]]
    assert [e["run_id"] for e in outside] == ["20260926-1413"]
    # Runs outside the chain never move the origin.
    assert core["origins"]["working-language"]["kind"] == "carried"


def _opp_run(run_id: str, rows: list[dict], *, in_lineage: bool = False,
             via: str = "") -> ChainRun:
    return ChainRun("ws", OPP, run_id, via=via, rows=rows, in_lineage=in_lineage,
                    date=f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}")


_OTHER = {"id": "unrelated", "ai-default": "x", "status": "ai-default"}


def test_scope_opp_drops_runs_from_before_the_decision_existed():
    """Runs older than the first one with the decision are noise (the
    spark-facilitator `gps-per-meeting-capture` case: 14 leading misses)."""
    head = _opp_run("20260110-0900", [{"id": "rate", "ai-default": "6"}],
                    in_lineage=True, via="forked")
    parent = _opp_run("20260109-0900", [{"id": "rate", "ai-default": "5"}], in_lineage=True)
    before = [_opp_run(f"2026010{d}-0900", [_OTHER]) for d in range(1, 9)]
    core = build_lineage([head, parent], before)
    hist = core["histories"]["rate"]
    assert [e["run_id"] for e in hist] == ["20260109-0900", "20260110-0900"]
    assert all(e["found"] for e in hist)


def test_a_run_missing_between_two_that_have_it_is_kept():
    head = _opp_run("20260105-0900", [{"id": "rate", "ai-default": "6"}],
                    in_lineage=True, via="forked")
    others = [
        _opp_run("20260104-0900", [_OTHER]),                       # the gap
        _opp_run("20260103-0900", [{"id": "rate", "ai-default": "5"}]),
        _opp_run("20260102-0900", [_OTHER]),                       # leading
        _opp_run("20260101-0900", [_OTHER]),                       # leading
    ]
    hist = build_lineage([head], others)["histories"]["rate"]
    assert [(e["run_id"], e["found"]) for e in hist] == [
        ("20260103-0900", True),
        ("20260104-0900", False),
        ("20260105-0900", True),
    ]


def test_no_earlier_match_keeps_every_run_that_was_searched():
    head = _opp_run("20260104-0900", [{"id": "rate", "ai-default": "6"}],
                    in_lineage=True, via="forked")
    parent = _opp_run("20260103-0900", [_OTHER], in_lineage=True)
    others = [_opp_run("20260102-0900", [_OTHER]), _opp_run("20260101-0900", [_OTHER])]
    core = build_lineage([head, parent], others)
    hist = core["histories"]["rate"]
    assert [e["found"] for e in hist] == [False, False, False, True]
    assert core["origins"]["rate"]["kind"] == "new"


def test_a_decision_only_newer_runs_share_keeps_this_runs_entry():
    head = _opp_run("20260102-0900", [{"id": "rate", "ai-default": "6"}], in_lineage=True)
    others = [
        _opp_run("20260103-0900", [{"id": "rate", "ai-default": "7"}]),
        _opp_run("20260101-0900", [_OTHER]),
    ]
    hist = build_lineage([head], others)["histories"]["rate"]
    assert [(e["run_id"], e["found"]) for e in hist] == [
        ("20260102-0900", True),
        ("20260103-0900", True),
    ]
    assert hist[0]["current"] is True


def test_a_run_with_no_lineage_has_only_new_and_human_rows():
    core = build_lineage([_run("dimagi-team", "20260925-1536")])
    assert set(core["counts"]) >= {"new", "human"}
    assert core["counts"]["carried"] == core["counts"]["changed"] == 0


# ─── Parent resolution ──────────────────────────────────────────────


def test_a_clone_block_wins_over_the_copied_forked_from():
    """A clone copies run_state verbatim, so its `forked_from` names the
    SOURCE's parent; the clone's real parent is the source run."""
    state = yaml.safe_load(_text("spark", RUN, "run_state.yaml"))
    assert parent_of(state, workspace="spark", opp=OPP) == (
        "dimagi-team", OPP, RUN, "cloned", "",
    )


def test_a_seeded_fork_names_its_phase():
    state = yaml.safe_load(_text("dimagi-team", RUN, "run_state.yaml"))
    assert parent_of(state, workspace="dimagi-team", opp=OPP) == (
        "dimagi-team", OPP, "20260926-1800", "seeded", "commcare-setup",
    )


def test_the_root_has_no_parent():
    state = yaml.safe_load(_text("dimagi-team", "20260925-1536", "run_state.yaml"))
    assert parent_of(state, workspace="dimagi-team", opp=OPP) is None


# ─── Drive walk + endpoint ──────────────────────────────────────────


def _run_tree(ws: str, runs: list[str]) -> dict:
    return {OPP: {"runs": {
        r: {
            "run_state.yaml": _text(ws, r, "run_state.yaml"),
            "decisions.yaml": _text(ws, r, "decisions.yaml"),
        } for r in runs
    }}}


def _two_workspace_drive() -> FakeDriveClient:
    return FakeDriveClient.from_tree({
        "DT": _run_tree("dimagi-team", [RUN, "20260926-1800", "20260925-1536", "20260926-1413"]),
        "SPARK": _run_tree("spark", [RUN]),
    })


def test_load_chain_crosses_into_the_clone_source_workspace():
    drive = _two_workspace_drive()
    roots = {"dimagi-team": drive.folder_id("DT"), "spark": drive.folder_id("SPARK")}
    chain = load_chain(lambda ws: (drive, roots[ws]) if ws in roots else None,
                       workspace="spark", opp=OPP, run_id=RUN)
    assert [(r.workspace, r.run_id, r.via, r.at_phase) for r in chain] == [
        ("spark", RUN, "cloned", ""),
        ("dimagi-team", RUN, "seeded", "commcare-setup"),
        ("dimagi-team", "20260926-1800", "forked", "synthetic-data-and-workflows"),
        ("dimagi-team", "20260925-1536", "", ""),
    ]
    assert chain[0].date == "2026-10-01"


def test_an_unknown_source_workspace_is_named_but_not_read():
    drive = _two_workspace_drive()
    chain = load_chain(lambda ws: (drive, drive.folder_id("SPARK")) if ws == "spark" else None,
                       workspace="spark", opp=OPP, run_id=RUN)
    assert [(r.workspace, r.readable) for r in chain] == [("spark", True), ("dimagi-team", False)]


def test_a_cycle_in_lineage_pointers_stops():
    tree = {"R": {OPP: {"runs": {
        "20260101-0900": {"run_state.yaml": "forked_from: '20260102-0900'\n"},
        "20260102-0900": {"run_state.yaml": "forked_from: '20260101-0900'\n"},
    }}}}
    drive = FakeDriveClient.from_tree(tree)
    chain = load_chain(lambda ws: (drive, drive.folder_id("R")),
                       workspace="w", opp=OPP, run_id="20260101-0900")
    assert [r.run_id for r in chain] == ["20260101-0900", "20260102-0900"]


@pytest.fixture
def lineage_workspaces(db, monkeypatch):
    from django.core.cache import cache

    cache.clear()
    drive = _two_workspace_drive()
    creator = User.objects.create_user(email="lineage-creator@example.com")
    dt = Workspace.objects.create(slug="dimagi-team", display_name="Dimagi",
                                  drive_root_folder_id=drive.folder_id("DT"), created_by=creator)
    spark = Workspace.objects.create(slug="spark", display_name="Spark",
                                     drive_root_folder_id=drive.folder_id("SPARK"),
                                     created_by=creator)
    monkeypatch.setattr("apps.opps.drive_client.get_drive_client",
                        lambda workspace=None: drive)
    return dt, spark


_URL = f"/api/opps/public/spark/{OPP}/runs/{RUN}/lineage"


@pytest.mark.django_db
def test_an_outsider_gets_the_strip_and_badges_in_plain_words(client, lineage_workspaces):
    body = client.get(_URL).json()
    assert body["viewer"] == {"is_member": False, "plain": True}
    assert [s["via"] for s in body["chain"]] == ["cloned", "seeded", "forked", ""]
    # No run plumbing for a non-member: no ids, no workspaces, no links, no history.
    for step in body["chain"]:
        assert step["run_id"] is None and step["workspace"] is None
        assert step["workbench_url"] is None and step["summary_url"] is None
    assert body["chain"][1]["stage"] == "app build"
    assert body["histories"] == {}
    o = body["origins"]["working-language"]
    assert o["kind"] == "carried" and o["from_run"] is None
    assert o["from_date"] == "2026-09-25"


@pytest.mark.django_db
def test_a_clone_member_sees_the_source_as_a_label_not_a_link(client, lineage_workspaces):
    _dt, spark = lineage_workspaces
    user = User.objects.create_user(email="spark-admin@example.org")
    WorkspaceMembership.objects.create(workspace=spark, user=user, role="admin")
    client.force_login(user)
    body = client.get(_URL).json()
    assert body["viewer"] == {"is_member": True, "plain": False}
    head, source = body["chain"][0], body["chain"][1]
    assert head["workbench_url"] == f"/w/spark/opps/{OPP}/runs/{RUN}"
    assert source["workspace"] == "dimagi-team" and source["run_id"] == RUN
    assert source["workbench_url"] is None and source["summary_url"] is None
    hist = body["histories"]["working-language"]
    # Three runs, the last one this run (folded into the source it copies).
    assert [e["linked"] for e in hist] == [False, False, False]
    assert hist[-1]["current"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_a_member_below_admin_gets_the_partner_shape(client, lineage_workspaces, role):
    """Below ``summary.team_view`` (admin), a member — an editor (how
    partner reviewers are invited) or a viewer — is drawn the PARTNER view:
    the same plain shape an outsider gets — no run ids, no history, no
    links, no ``scope=opp``."""
    _dt, spark = lineage_workspaces
    user = User.objects.create_user(email=f"partner-{role}@example.org")
    WorkspaceMembership.objects.create(workspace=spark, user=user, role=role)
    client.force_login(user)
    body = client.get(_URL).json()
    assert body["viewer"] == {"is_member": True, "plain": True}
    for step in body["chain"]:
        assert step["run_id"] is None and step["workspace"] is None
        assert step["at_phase"] == ""
        assert step["workbench_url"] is None and step["summary_url"] is None
    assert body["histories"] == {}
    o = body["origins"]["working-language"]
    assert o["from_run"] is None and o["in_run"] is None
    assert o["from_date"] == "2026-09-25"
    assert client.get(f"{_URL}?scope=opp").json()["scope"] == "lineage"


@pytest.mark.django_db
def test_an_owner_gets_the_team_shape(client, lineage_workspaces):
    _dt, spark = lineage_workspaces
    user = User.objects.create_user(email="spark-owner@example.org")
    WorkspaceMembership.objects.create(workspace=spark, user=user, role="owner")
    client.force_login(user)
    body = client.get(_URL).json()
    assert body["viewer"] == {"is_member": True, "plain": False}
    assert body["chain"][0]["run_id"] == RUN
    assert body["chain"][0]["workbench_url"] == f"/w/spark/opps/{OPP}/runs/{RUN}"
    assert body["histories"]["working-language"]


@pytest.mark.django_db
def test_a_member_of_both_workspaces_gets_links_all_the_way_back(client, lineage_workspaces):
    dt, spark = lineage_workspaces
    user = User.objects.create_user(email="staff@dimagi.com")
    for ws in (dt, spark):
        WorkspaceMembership.objects.create(workspace=ws, user=user, role="admin")
    client.force_login(user)
    body = client.get(_URL).json()
    assert all(s["workbench_url"] for s in body["chain"])
    assert body["chain"][2]["summary_url"] == (
        f"/opps/dimagi-team/{OPP}/runs/20260926-1800/summary"
    )


@pytest.mark.django_db
def test_scope_opp_is_members_only(client, lineage_workspaces):
    dt, _spark = lineage_workspaces
    url = f"/api/opps/public/dimagi-team/{OPP}/runs/{RUN}/lineage?scope=opp"
    assert client.get(url).json()["scope"] == "lineage"
    user = User.objects.create_user(email="staff2@dimagi.com")
    WorkspaceMembership.objects.create(workspace=dt, user=user, role="admin")
    client.force_login(user)
    body = client.get(url).json()
    assert body["scope"] == "opp"
    outside = [e for e in body["histories"]["working-language"] if not e["in_lineage"]]
    assert [e["run_id"] for e in outside] == ["20260926-1413"]


@pytest.mark.django_db
def test_a_run_clone_row_stands_in_for_a_missing_clone_block(
    client, lineage_workspaces, monkeypatch,
):
    """A clone whose run_state was never stamped still finds its source."""
    dt, spark = lineage_workspaces
    RunClone.objects.create(source_workspace=dt, target_workspace=spark, opp_slug=OPP,
                            run_id=RUN, status="done")
    drive = FakeDriveClient.from_tree({
        "DT": _run_tree("dimagi-team", [RUN, "20260926-1800", "20260925-1536"]),
        "SPARK": {OPP: {"runs": {RUN: {
            "run_state.yaml": f"run_id: '{RUN}'\n",
            "decisions.yaml": _text("spark", RUN, "decisions.yaml"),
        }}}},
    })
    dt.drive_root_folder_id = drive.folder_id("DT")
    dt.save()
    spark.drive_root_folder_id = drive.folder_id("SPARK")
    spark.save()
    monkeypatch.setattr("apps.opps.drive_client.get_drive_client",
                        lambda workspace=None: drive)
    body = client.get(_URL).json()
    assert body["chain"][0]["via"] == "cloned"
    assert len(body["chain"]) == 4


@pytest.mark.django_db
def test_an_unknown_run_is_a_404(client, lineage_workspaces):
    assert client.get(f"/api/opps/public/spark/{OPP}/runs/nope/lineage").status_code == 404
    assert client.get(f"/api/opps/public/nope/{OPP}/runs/{RUN}/lineage").status_code == 404


def test_shape_never_shows_an_outsider_an_email():
    core = build_lineage([ChainRun("w", OPP, "20260101-0900", rows=[
        {"id": "x", "ai-default": "a", "override": "b", "status": "human-decided",
         "decided_by": "someone@example.org", "decided_at": "2026-01-02"},
    ])])
    out = shape_for_viewer(core, member=False, accessible=set())
    assert out["origins"]["x"]["by"] == "a reviewer"
    assert out["origins"]["x"]["at"] == "2026-01-02"


# ─── A clone of a FRESH run (spark/20261004-1706) ───────────────────
#
# Modelled on the live case of 2026-10-08: dimagi-team/20261004-1706 was an
# independent /ace:run (no forked_from / seeded_from, no inherited_from_run on
# any row); spark/20261004-1706 is a clone of it that re-minted the Connect
# rows for the partner's own orgs — the original kept as `<id>-dimagi-team`,
# superseded by a fresh `<id>` (same value, or a new one where the partner's
# Connect differs). Before the fix every row read "carried from
# 20261004-1706" (an earlier run decided it — false) or "re-affirmed (same as
# dimagi-team / 20261004-1706)", and opp-scope history missed the dimagi-team
# runs where the value actually evolved.

FRESH = "20261004-1706"
GPS = "gps-per-meeting-capture"
RULE = "connect-rule-one-paid-per-worker-per-day"


def _decisions(*rows: dict) -> str:
    return yaml.safe_dump({"decisions": list(rows)})


def _d(rid: str, value: str, **extra) -> dict:
    return {"id": rid, "ai-default": value, "status": "ai-default", **extra}


def _clone_state(run: str) -> str:
    return (f"run_id: '{run}'\ncreated: '2026-10-04T17:06:00+00:00'\n"
            f"clone:\n  from: {{workspace: dimagi-team, opp: {OPP}, run: '{run}'}}\n")


_SOURCE_ROWS = [
    _d("working-language", "English"),
    _d(GPS, "Captured with accuracy, optional, advisory only"),
    _d(RULE, "Connect payment unit limit"),
    _d("connect-opportunity", "dimagi-ace-pm opportunity 812"),
]

_CLONE_ROWS = [
    _d("working-language", "English"),
    _d(GPS, "Captured with accuracy, optional, advisory only"),
    # The re-mint: same value under the same id, the original kept aside.
    _d(f"{RULE}-dimagi-team", "Connect payment unit limit", superseded_by=RULE,
       inherited_from_run=FRESH),
    _d(RULE, "Connect payment unit limit"),
    # A re-mint that DID change the value: the partner's own opportunity.
    _d("connect-opportunity-dimagi-team", "dimagi-ace-pm opportunity 812",
       superseded_by="connect-opportunity", inherited_from_run=FRESH),
    _d("connect-opportunity", "spark-pm opportunity 905"),
    # Written in the clone only.
    _d("wo-fixed-costs-fee-structure", "Per-meeting fee only"),
]


def _fresh_clone_tree() -> dict:
    def run(state: str, *rows: dict) -> dict:
        return {"run_state.yaml": state, "decisions.yaml": _decisions(*rows)}

    return {
        "DT": {OPP: {"runs": {
            # Independent earlier runs, where the GPS answer actually evolved.
            "20260910-1624": run("run_id: '20260910-1624'\n",
                                 _d(GPS, "Captured with accuracy, advisory only")),
            "20260926-1413": run("run_id: '20260926-1413'\n",
                                 _d(GPS, "Captured with accuracy, review only")),
            "20261001-2208": run("run_id: '20261001-2208'\n",
                                 _d(GPS, "Captured with accuracy, advisory only")),
            FRESH: run(f"run_id: '{FRESH}'\ncreated: '2026-10-04T17:06:00+00:00'\n",
                       *_SOURCE_ROWS),
        }}},
        "SPARK": {OPP: {"runs": {
            # An older clone of dimagi-team's 2208: the same run, not another.
            "20261001-2208": run(_clone_state("20261001-2208"),
                                 _d(GPS, "Captured with accuracy, advisory only")),
            FRESH: run(_clone_state(FRESH), *_CLONE_ROWS),
        }}},
    }


def _fresh_chain() -> list[ChainRun]:
    return [
        ChainRun("spark", OPP, FRESH, "cloned", date="2026-10-04", rows=_CLONE_ROWS,
                 copied_date="2026-10-06"),
        ChainRun("dimagi-team", OPP, FRESH, date="2026-10-04", rows=_SOURCE_ROWS),
    ]


@pytest.fixture(scope="module")
def fresh_core() -> dict:
    return build_lineage(_fresh_chain())


def test_a_clone_of_a_fresh_run_traces_to_the_run_that_decided_it(fresh_core):
    """Never "carried": the source decided these itself, in that run."""
    for rid in ("working-language", GPS):
        o = fresh_core["origins"][rid]
        assert o["kind"] == "decided", rid
        assert (o["from_workspace"], o["from_run"]) == ("dimagi-team", FRESH)
        assert (o["in_workspace"], o["in_run"]) == ("dimagi-team", FRESH)


def test_a_clone_re_mint_with_the_same_value_is_not_an_event(fresh_core):
    """`<id>-dimagi-team` superseded by a same-value `<id>` reads exactly like
    an unchanged row — not "re-affirmed (same as dimagi-team / …)"."""
    o = fresh_core["origins"][RULE]
    assert o["kind"] == "decided"
    assert o["from_run"] == FRESH and o["from_workspace"] == "dimagi-team"


def test_a_clone_re_mint_that_changed_the_value_says_the_copy_changed_it(fresh_core):
    o = fresh_core["origins"]["connect-opportunity"]
    assert o["kind"] == "changed" and o["on_copy"] is True
    assert o["previous_value"] == "dimagi-ace-pm opportunity 812"
    assert (o["in_workspace"], o["from_workspace"]) == ("spark", "dimagi-team")


def test_a_row_written_only_in_the_clone_is_new_here(fresh_core):
    assert fresh_core["origins"]["wo-fixed-costs-fee-structure"]["kind"] == "new"


def test_a_clone_of_a_fresh_run_has_no_carried_or_reaffirmed_rows(fresh_core):
    counts = fresh_core["counts"]
    assert counts["carried"] == counts["reaffirmed"] == 0
    assert counts == {"new": 1, "decided": 3, "carried": 0, "changed": 1,
                      "reaffirmed": 0, "human": 0}
    live = [r for r in _CLONE_ROWS if not r.get("superseded_by")]
    assert sum(counts.values()) == len(live)


def test_a_clone_and_its_source_are_one_history_entry(fresh_core):
    hist = fresh_core["histories"][GPS]
    assert [(e["workspace"], e["run_id"]) for e in hist] == [("dimagi-team", FRESH)]
    assert hist[0]["current"] is True
    assert hist[0]["copied_to"] == [{"workspace": "spark", "date": "2026-10-06"}]
    # A copy that changed the value is two entries: that is a real change.
    changed = fresh_core["histories"]["connect-opportunity"]
    assert [e["workspace"] for e in changed] == ["dimagi-team", "spark"]


def test_shape_points_a_decided_origin_at_the_source_step(fresh_core):
    out = shape_for_viewer(fresh_core, member=True, accessible={"spark"})
    o = out["origins"][GPS]
    assert (o["kind"], o["from_position"], o["in_position"]) == ("decided", 1, 1)
    assert o["from_run"] == FRESH and o["in_date"] == "2026-10-04"
    assert out["chain"][0]["copied_date"] == "2026-10-06"
    outsider = shape_for_viewer(fresh_core, member=False, accessible=set())
    assert outsider["origins"][GPS]["in_run"] is None
    assert outsider["origins"][GPS]["in_position"] == 1


@pytest.fixture
def fresh_workspaces(db, monkeypatch):
    from django.core.cache import cache

    cache.clear()
    drive = FakeDriveClient.from_tree(_fresh_clone_tree())
    creator = User.objects.create_user(email="fresh-creator@example.com")
    dt = Workspace.objects.create(slug="dimagi-team", display_name="Dimagi",
                                  drive_root_folder_id=drive.folder_id("DT"), created_by=creator)
    spark = Workspace.objects.create(slug="spark", display_name="Spark",
                                     drive_root_folder_id=drive.folder_id("SPARK"),
                                     created_by=creator)
    monkeypatch.setattr("apps.opps.drive_client.get_drive_client",
                        lambda workspace=None: drive)
    return dt, spark


@pytest.mark.django_db
def test_scope_opp_on_a_clone_reads_the_source_workspaces_runs(client, fresh_workspaces):
    """The GPS answer evolved across dimagi-team's independent runs; a spark
    member asking for opp-wide history of the clone must see them, with the
    older spark clone folded into its dimagi-team source."""
    dt, spark = fresh_workspaces
    RunClone.objects.create(source_workspace=dt, target_workspace=spark, opp_slug=OPP,
                            run_id=FRESH, status="done")
    user = User.objects.create_user(email="both@dimagi.com")
    for ws in (dt, spark):
        WorkspaceMembership.objects.create(workspace=ws, user=user, role="admin")
    client.force_login(user)
    body = client.get(f"/api/opps/public/spark/{OPP}/runs/{FRESH}/lineage?scope=opp").json()
    assert body["scope"] == "opp"
    hist = body["histories"][GPS]
    assert [(e["workspace"], e["run_id"]) for e in hist] == [
        ("dimagi-team", "20260910-1624"),
        ("dimagi-team", "20260926-1413"),
        ("dimagi-team", "20261001-2208"),
        ("dimagi-team", FRESH),
    ]
    assert [e["value"] for e in hist] == [
        "Captured with accuracy, advisory only",
        "Captured with accuracy, review only",
        "Captured with accuracy, advisory only",
        "Captured with accuracy, optional, advisory only",
    ]
    # Each clone is folded into its source — no run appears twice.
    assert [c["workspace"] for c in hist[2]["copied_to"]] == ["spark"]
    assert hist[-1]["current"] is True and hist[-1]["copied_to"][0]["workspace"] == "spark"
    # Other runs never move the origin.
    assert body["origins"][GPS]["kind"] == "decided"
    assert body["counts"]["carried"] == body["counts"]["reaffirmed"] == 0
    # The copy date comes from the RunClone row when the stamp has none.
    assert body["chain"][0]["copied_date"]
