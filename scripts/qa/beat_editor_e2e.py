"""End-to-end smoke test for the React beat editor (Phase 1).

Walks the full beat-editor flow against a deployed (or local) ace-web:

  1. Seed step — "generate a CHC video": the canonical generation path is
     ``/ace:video-from-program-page https://labs.connect.dimagi.com/programs/chc``
     run from a Claude session (LLM-driven; reads the program page,
     fills the 60s-campaign-overview template, POSTs to
     ``/api/w/<ws>/videos/programs``). Because that step is non-
     deterministic and slow, this script seeds the program by POSTing
     the in-repo ``video-production/connect-videos/programs/chc/runs/
     run-001/spec.yaml`` directly (idempotent — skipped if program
     already exists). The deterministic POST is the same final action
     the skill takes, so the rest of the flow is identical to running
     the skill for real.

  2. UI walk:
     - Navigate to ``/w/<workspace>/videos/<slug>``
     - Verify the React ``<BeatEditor>`` renders (not the legacy iframe)
     - For each widget kind in the spec, open the drawer, make an edit,
       click Done → buffer increments
     - Click Save Changes → ``POST /edit-batch`` succeeds → buffer clears
     - GET the run-detail endpoint → confirm the new YAML reflects edits
     - Optional: trigger Re-render and poll until done

Auth
====
Two paths supported, picked from env:

  - ``LABS_TOKEN`` set → uses ``POST /auth/e2e-login/`` (labs, prod)
  - else → uses ``POST /auth/test-login/`` (local dev; requires
    ``ACE_ALLOW_TEST_LOGIN=True`` and ``DEBUG=True``)

Usage
=====
::

    # Against local dev (docker compose up):
    BASE=http://localhost:8000 uv run --extra walkthrough \
        python scripts/qa/beat_editor_e2e.py

    # Against labs (requires ACE_VIDEO_BEAT_EDITOR_REACT=True on the task):
    BASE=https://labs.connect.dimagi.com/ace \
    LABS_TOKEN=$(op read 'op://Engineering/ace-web e2e token/credential') \
    uv run --extra walkthrough python scripts/qa/beat_editor_e2e.py

Output
======
::

    qa-results/<UTC-iso>/beat-editor/
        report.json
        report.md
        <step-name>.png      full-page screenshots per assertion point
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import Page, sync_playwright, expect
except ImportError:
    print("Run with `uv run --extra walkthrough`", file=sys.stderr)
    sys.exit(2)


BASE = os.environ.get("BASE", os.environ.get("LABS_URL", "https://labs.connect.dimagi.com/ace")).rstrip("/")
TOKEN = os.environ.get("LABS_TOKEN", "")
EMAIL = os.environ.get("LABS_EMAIL", "ace@dimagi-ai.com")
WORKSPACE = os.environ.get("WORKSPACE", os.environ.get("LABS_WORKSPACE", "dimagi-team"))
SLUG = os.environ.get("PROGRAM_SLUG", "chc")
TRIGGER_RERENDER = os.environ.get("TRIGGER_RERENDER") == "1"

REPO = Path(__file__).resolve().parents[2]
SEED_SPEC = REPO / "video-production" / "connect-videos" / "programs" / SLUG / "runs" / "run-001" / "spec.yaml"
RUN_ID = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
OUT = REPO / "qa-results" / RUN_ID / "beat-editor"


@dataclass
class StepResult:
    name: str
    verdict: str = "pending"  # ok | broken | fatal | skipped
    detail: str = ""
    screenshot: str = ""
    bad_responses: list[dict[str, Any]] = field(default_factory=list)
    js_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "verdict": self.verdict,
            "detail": self.detail,
            "screenshot": self.screenshot,
            "bad_responses": self.bad_responses,
            "js_errors": self.js_errors,
        }


def _capture(page: Page) -> tuple[list, list]:
    bad: list[dict] = []
    errs: list[str] = []
    page.on(
        "response",
        lambda r: bad.append({
            "status": r.status,
            "method": r.request.method,
            "url": r.url[r.url.find("/api"):] if "/api/" in r.url else r.url[r.url.rfind("/"):],
        }) if r.status >= 400 else None,
    )
    page.on("console", lambda m: errs.append(f"[{m.type}] {m.text[:200]}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errs.append(f"[pageerror] {str(e)[:200]}"))
    return bad, errs


def _screenshot(page: Page, name: str) -> str:
    """Save a full-page screenshot and return its repo-relative path."""
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(REPO))


def login(ctx) -> bool:
    """Hit /auth/e2e-login/ (labs) or /auth/test-login/ (dev) for a session cookie."""
    if TOKEN:
        resp = ctx.request.post(
            f"{BASE}/auth/e2e-login/",
            data=json.dumps({"email": EMAIL, "token": TOKEN}),
            headers={"Content-Type": "application/json"},
        )
        if resp.status != 200:
            print(f"[auth] e2e-login FAILED status={resp.status} body={resp.text()[:200]}", file=sys.stderr)
            return False
        print(f"[auth] OK via e2e-login ({EMAIL})")
        return True

    # Dev fallback — test-login (only enabled when DEBUG + ACE_ALLOW_TEST_LOGIN).
    resp = ctx.request.post(
        f"{BASE}/auth/test-login/",
        data=json.dumps({"email": EMAIL, "display_name": "ACE Bot"}),
        headers={"Content-Type": "application/json"},
    )
    if resp.status != 200:
        print(
            f"[auth] test-login FAILED status={resp.status} body={resp.text()[:200]}\n"
            "  Set LABS_TOKEN for labs, or ensure ACE_ALLOW_TEST_LOGIN=True + DEBUG=True locally.",
            file=sys.stderr,
        )
        return False
    print(f"[auth] OK via test-login ({EMAIL})")
    return True


def ensure_program(ctx) -> StepResult:
    """Idempotently seed the CHC program from the in-repo spec.yaml.

    Skipped if program already exists in the target workspace.
    """
    r = StepResult(name="00-seed-program")

    # Already there?
    resp = ctx.request.get(f"{BASE}/api/w/{WORKSPACE}/videos/programs/{SLUG}")
    if resp.status == 200:
        r.verdict = "skipped"
        r.detail = f"program {SLUG} already exists in {WORKSPACE}"
        return r

    if not SEED_SPEC.exists():
        r.verdict = "fatal"
        r.detail = f"seed spec not found at {SEED_SPEC}"
        return r

    spec_yaml = SEED_SPEC.read_text()
    # The spec hard-codes `workspace: dimagi-team` — if WORKSPACE differs,
    # rewrite the line. Crude but safe (the field is a top-level scalar).
    if WORKSPACE != "dimagi-team":
        spec_yaml = spec_yaml.replace("workspace: dimagi-team", f"workspace: {WORKSPACE}")

    resp = ctx.request.post(
        f"{BASE}/api/w/{WORKSPACE}/videos/programs",
        data=json.dumps({"slug": SLUG, "spec_yaml": spec_yaml}),
        headers={"Content-Type": "application/json"},
    )
    if resp.status not in (200, 201):
        r.verdict = "fatal"
        r.detail = f"create_program returned {resp.status}: {resp.text()[:200]}"
        return r

    r.verdict = "ok"
    r.detail = f"seeded {SLUG} from in-repo spec ({len(spec_yaml)} bytes)"
    return r


# ---------------------------------------------------------------------------
# UI assertions
# ---------------------------------------------------------------------------

EDITOR_ROOT_SELECTOR = "[data-beat-id]"   # BeatCard has data-beat-id
IFRAME_FALLBACK_SELECTOR = "iframe"


def step_open_editor(page: Page) -> StepResult:
    """Navigate to the editor and verify the React surface (not iframe)."""
    r = StepResult(name="01-open-editor")
    url = f"{BASE}/w/{WORKSPACE}/videos/{SLUG}"
    bad, errs = _capture(page)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        # A BeatCard with data-beat-id means React tree is mounted.
        has_react = page.locator(EDITOR_ROOT_SELECTOR).count() > 0
        has_iframe = page.locator(IFRAME_FALLBACK_SELECTOR).count() > 0
        r.screenshot = _screenshot(page, r.name)
        if has_react:
            beats = page.locator(EDITOR_ROOT_SELECTOR).count()
            r.verdict = "ok"
            r.detail = f"React editor rendered with {beats} beat cards"
        elif has_iframe:
            r.verdict = "broken"
            r.detail = (
                "Iframe rendered instead of React editor — "
                "ACE_VIDEO_BEAT_EDITOR_REACT is likely False on this deployment."
            )
        else:
            r.verdict = "broken"
            r.detail = "Neither React nor iframe surface found"
    except Exception as e:
        r.verdict = "fatal"
        r.detail = str(e)[:300]
    r.bad_responses = bad
    r.js_errors = errs
    return r


def step_edit_narration(page: Page) -> StepResult:
    """Click a narration widget, type new text, click Done. Buffer +1."""
    r = StepResult(name="02-edit-narration")
    bad, errs = _capture(page)
    try:
        # First narration widget (every beat has one).
        narration = page.locator("text=Voiceover").first
        narration.click()
        page.wait_for_timeout(400)
        textarea = page.locator("aside[role='dialog'] textarea, div[role='dialog'] textarea").first
        textarea.fill("E2E-EDITED narration line for the beat editor smoke test.")
        page.get_by_role("button", name="Done").click()
        page.wait_for_timeout(400)
        # The top-bar should now show "1 edit pending".
        expect(page.get_by_text("edit pending", exact=False)).to_be_visible(timeout=3000)
        r.screenshot = _screenshot(page, r.name)
        r.verdict = "ok"
        r.detail = "narration drawer opened, edited, committed to buffer"
    except Exception as e:
        r.verdict = "broken"
        r.detail = str(e)[:300]
        r.screenshot = _screenshot(page, r.name)
    r.bad_responses = bad
    r.js_errors = errs
    return r


def step_edit_stat(page: Page) -> StepResult:
    """Click a stats widget (problem or impact[N]), edit big number, Done."""
    r = StepResult(name="03-edit-stat")
    bad, errs = _capture(page)
    try:
        # StatsWidget renders the big number large — click any one.
        stat_card = page.locator("div").filter(has_text="source:").first
        if stat_card.count() == 0:
            # Fallback: click any "click to edit" element whose neighbor has a big number
            stat_card = page.get_by_text("click to edit").first
        stat_card.click()
        page.wait_for_timeout(400)
        big_input = page.get_by_label("big", exact=False).first
        big_input.fill("E2E-99%")
        page.get_by_role("button", name="Done").click()
        page.wait_for_timeout(400)
        # Pending count should now be ≥ 2 (narration + stat).
        expect(page.get_by_text("edit", exact=False)).to_be_visible()
        r.screenshot = _screenshot(page, r.name)
        r.verdict = "ok"
        r.detail = "stat drawer opened, big edited, committed to buffer"
    except Exception as e:
        r.verdict = "broken"
        r.detail = str(e)[:300]
        r.screenshot = _screenshot(page, r.name)
    r.bad_responses = bad
    r.js_errors = errs
    return r


def step_save(page: Page) -> StepResult:
    """Click Save changes; assert POST /edit-batch succeeds and buffer clears."""
    r = StepResult(name="04-save")
    bad, errs = _capture(page)
    try:
        # Watch for the /edit-batch response specifically.
        edit_batch_resp: dict[str, Any] = {}
        def on_resp(resp):
            if "/edit-batch" in resp.url:
                edit_batch_resp["status"] = resp.status
                edit_batch_resp["url"] = resp.url
        page.on("response", on_resp)

        page.get_by_role("button", name="Save changes").click()
        # Wait for either "Saved at" or "Save failed".
        page.wait_for_timeout(3500)
        r.screenshot = _screenshot(page, r.name)

        if edit_batch_resp.get("status") in (200, 201):
            saved_label_visible = page.locator("text=Saved at").count() > 0
            r.verdict = "ok" if saved_label_visible else "broken"
            r.detail = (
                f"/edit-batch -> {edit_batch_resp['status']}; "
                f"TopBar 'Saved at' visible={saved_label_visible}"
            )
        else:
            r.verdict = "broken"
            r.detail = f"/edit-batch did not return 200; got {edit_batch_resp.get('status')!r}"
    except Exception as e:
        r.verdict = "broken"
        r.detail = str(e)[:300]
        r.screenshot = _screenshot(page, r.name)
    r.bad_responses = bad
    r.js_errors = errs
    return r


def step_verify_persisted(ctx) -> StepResult:
    """GET the run detail and confirm our edits are in the YAML."""
    r = StepResult(name="05-verify-persisted")
    resp = ctx.request.get(f"{BASE}/api/w/{WORKSPACE}/videos/programs/{SLUG}/runs/run-001")
    if resp.status != 200:
        r.verdict = "broken"
        r.detail = f"GET run detail returned {resp.status}"
        return r
    body = resp.json()
    spec = body.get("spec") or {}
    nar = (spec.get("narration") or {}).get("by_beat") or {}
    nar_str = json.dumps(nar)
    problem = (spec.get("problem") or {}).get("big") or ""
    impact_bigs = [item.get("big", "") for item in (spec.get("impact") or [])]
    nar_hit = "E2E-EDITED" in nar_str
    stat_hit = "E2E-99%" in problem or any("E2E-99%" in b for b in impact_bigs)
    if nar_hit and stat_hit:
        r.verdict = "ok"
        r.detail = "narration and stat edits both persisted in YAML"
    elif nar_hit or stat_hit:
        r.verdict = "broken"
        r.detail = (
            f"partial persistence: narration={nar_hit} stat={stat_hit}; "
            f"problem.big={problem!r} impact_bigs={impact_bigs!r}"
        )
    else:
        r.verdict = "broken"
        r.detail = (
            f"no edits found in saved YAML: "
            f"problem.big={problem!r} impact_bigs={impact_bigs!r} "
            f"narration={nar_str[:120]}"
        )
    return r


def step_trigger_rerender(ctx) -> StepResult:
    """Optional: kick off a render and poll until busy clears."""
    r = StepResult(name="06-rerender")
    if not TRIGGER_RERENDER:
        r.verdict = "skipped"
        r.detail = "set TRIGGER_RERENDER=1 to enable"
        return r

    resp = ctx.request.post(
        f"{BASE}/api/w/{WORKSPACE}/videos/programs/{SLUG}/runs/run-001/build",
        data=json.dumps({"mode": "render"}),
        headers={"Content-Type": "application/json"},
    )
    if resp.status != 200:
        r.verdict = "broken"
        r.detail = f"build returned {resp.status}: {resp.text()[:200]}"
        return r

    # Poll up to 5 min for busy to clear.
    deadline = time.time() + 300
    while time.time() < deadline:
        s = ctx.request.get(f"{BASE}/api/w/{WORKSPACE}/videos/programs/{SLUG}/runs/run-001/render-status")
        if s.status == 200 and not s.json().get("busy", True):
            r.verdict = "ok"
            r.detail = "render completed"
            return r
        time.sleep(10)

    r.verdict = "broken"
    r.detail = "render still busy after 5 min"
    return r


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"[e2e] base={BASE} workspace={WORKSPACE} slug={SLUG} out={OUT.relative_to(REPO)}")

    results: list[StepResult] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        if not login(ctx):
            browser.close()
            return 2

        # Step 0 — seed the CHC program
        r = ensure_program(ctx)
        results.append(r)
        print(f"  [{r.verdict:7s}] {r.name}: {r.detail}")
        if r.verdict == "fatal":
            browser.close()
            return _finalize(results)

        # Step 1 — open editor + verify React surface
        page = ctx.new_page()
        r = step_open_editor(page)
        results.append(r)
        print(f"  [{r.verdict:7s}] {r.name}: {r.detail}")
        if r.verdict != "ok":
            page.close()
            browser.close()
            return _finalize(results)

        # Step 2 — narration edit
        r = step_edit_narration(page)
        results.append(r)
        print(f"  [{r.verdict:7s}] {r.name}: {r.detail}")

        # Step 3 — stat edit
        r = step_edit_stat(page)
        results.append(r)
        print(f"  [{r.verdict:7s}] {r.name}: {r.detail}")

        # Step 4 — save
        r = step_save(page)
        results.append(r)
        print(f"  [{r.verdict:7s}] {r.name}: {r.detail}")

        page.close()

        # Step 5 — verify persisted via GET (server-side truth)
        r = step_verify_persisted(ctx)
        results.append(r)
        print(f"  [{r.verdict:7s}] {r.name}: {r.detail}")

        # Step 6 — optional re-render
        r = step_trigger_rerender(ctx)
        results.append(r)
        print(f"  [{r.verdict:7s}] {r.name}: {r.detail}")

        browser.close()

    return _finalize(results)


def _finalize(results: list[StepResult]) -> int:
    summary = {
        "base": BASE,
        "workspace": WORKSPACE,
        "slug": SLUG,
        "run_id": RUN_ID,
        "counts": {
            "total": len(results),
            "ok":      sum(1 for r in results if r.verdict == "ok"),
            "skipped": sum(1 for r in results if r.verdict == "skipped"),
            "broken":  sum(1 for r in results if r.verdict == "broken"),
            "fatal":   sum(1 for r in results if r.verdict == "fatal"),
        },
        "results": [r.to_dict() for r in results],
    }
    (OUT / "report.json").write_text(json.dumps(summary, indent=2))
    _write_markdown(summary, OUT / "report.md")

    print("\n" + "=" * 72)
    print("BEAT EDITOR E2E — SUMMARY")
    print("=" * 72)
    c = summary["counts"]
    print(f"  total={c['total']} ok={c['ok']} skipped={c['skipped']} broken={c['broken']} fatal={c['fatal']}")
    print(f"  report: {OUT.relative_to(REPO)}/report.md")

    bad = [r for r in results if r.verdict in ("broken", "fatal")]
    if bad:
        print("\nFailures:")
        for r in bad:
            print(f"  ✗ {r.name}: {r.detail}")
            for b in r.bad_responses[:3]:
                print(f"      {b['status']} {b['method']} {b['url']}")
            for e in r.js_errors[:2]:
                print(f"      JS:  {e[:160]}")
        return 1
    return 0


def _write_markdown(summary: dict, path: Path) -> None:
    c = summary["counts"]
    lines = [
        f"# Beat Editor E2E — {summary['run_id']}",
        "",
        f"- Base: `{summary['base']}`",
        f"- Workspace: `{summary['workspace']}`",
        f"- Program: `{summary['slug']}`",
        f"- Total: {c['total']} | ✓ {c['ok']} | ⏭ {c['skipped']} | ✗ {c['broken']} | 💥 {c['fatal']}",
        "",
        "## Results",
        "",
        "| # | Step | Verdict | Detail |",
        "|---|------|---------|--------|",
    ]
    for i, r in enumerate(summary["results"], 1):
        detail = r["detail"][:90].replace("|", "/")
        lines.append(f"| {i} | `{r['name']}` | {r['verdict']} | {detail} |")
    bad = [r for r in summary["results"] if r["verdict"] in ("broken", "fatal")]
    if bad:
        lines += ["", "## Failures", ""]
        for r in bad:
            lines += [
                f"### {r['name']}",
                "",
                f"- Detail: {r['detail']}",
            ]
            if r["bad_responses"]:
                lines.append("- Bad responses:")
                for b in r["bad_responses"][:5]:
                    lines.append(f"  - `{b['status']} {b['method']} {b['url']}`")
            if r["js_errors"]:
                lines.append("- JS errors:")
                for e in r["js_errors"][:3]:
                    lines.append(f"  - `{e[:160]}`")
            if r["screenshot"]:
                lines.append(f"\n![{r['name']}](../../{r['screenshot']})\n")
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
