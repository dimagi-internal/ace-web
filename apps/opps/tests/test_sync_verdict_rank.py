"""Which verdict the Workbench shows when a skill wrote several.

`app-screenshot-capture` writes its FULL evaluation as
`app-screenshot-capture_verdict.yaml` and a one-dimension smoke pass beside it
as `_verdict-shallow.yaml`. The plain file ranked 0 and the shallow one 2, so
the smoke won: spark-facilitator/20260925-1536 showed a red "25" for a skill
whose full verdict was 9.2/10 (the smoke itself was a good 2.5 on its 0–3
scale — ACE now normalizes that too, ace#2563). Verdicts transcribed from that
run, trimmed.
"""
from apps.opps.sync import _load_verdicts
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient

FULL = """skill: app-screenshot-capture
ran_at: 2026-09-26T03:40:19.194Z
overall_score: 9.2
verdict: pass
dimensions:
  coverage: {score: 10, weight: 0.3}
  execution: {score: 10, weight: 0.3}
  artifact_quality: {score: 9, weight: 0.2}
  manifest_integrity: {score: 7, weight: 0.2}
"""
SHALLOW = """skill: app-screenshot-capture
mode: shallow
ran_at: 2026-09-26T03:40:19.194Z
overall_score: 2.5
verdict: pass
dimensions:
  ux_smoke: {score: 2.5, weight: 1}
"""
DEEP = """skill: app-screenshot-capture
mode: deep
ran_at: 2026-09-26T03:40:19.194Z
overall_score: 7.0
verdict: pass
"""


def _load(files: dict) -> dict:
    drive = FakeDriveClient.from_tree({"RUN": {"6-qa-and-training": files}})
    run = drive.folder_id("RUN")
    return _load_verdicts(drive, drive.list_files(run, recursive=True),
                          registered_skills={"app-screenshot-capture"})


def test_the_full_verdict_outranks_its_shallow_smoke():
    v = _load({
        "app-screenshot-capture_verdict.yaml": FULL,
        "app-screenshot-capture_verdict-shallow.yaml": SHALLOW,
    })["app-screenshot-capture"]
    assert v.score == 9.2  # the 4-dimension evaluation, not the 2.5 smoke


def test_a_deep_verdict_still_outranks_the_full_one():
    v = _load({
        "app-screenshot-capture_verdict.yaml": FULL,
        "app-screenshot-capture_verdict-deep.yaml": DEEP,
    })["app-screenshot-capture"]
    assert v.score == 7.0


def test_a_lone_shallow_verdict_is_still_shown():
    v = _load({"app-screenshot-capture_verdict-shallow.yaml": SHALLOW})["app-screenshot-capture"]
    assert v.score is not None
