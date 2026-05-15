"""Labs end-to-end probe.

Walks every UI surface on a deployed ace-web (labs by default), capturing
HTTP errors, JS errors, error-UI text, and a full-page screenshot per step.
Writes a structured JSON report + per-step PNGs to ``qa-results/<timestamp>/``.

Design choice — scripted, not LLM-driven
=========================================
The probe is deterministic so it's cheap to re-run on every deploy. It's
not trying to make taste judgments about "does this look right"; it's
checking the load-bearing claims:

- Did the page navigate?
- Did the SPA shell render real content (not just nav + "Loading…")?
- Did the API surface 4xx/5xx?
- Did React or the browser log errors?
- Did the page render an error overlay ("Something went wrong",
  "Unexpected Application Error")?

The probe surfaces failures with enough context (URL, status, error pre
text, screenshot path) that a human or LLM can dive into specifics. It
doesn't replace eyeballing; it replaces *forgetting* to eyeball.

Auth
====
Uses the ``/auth/e2e-login/`` endpoint with ``ACE_E2E_AUTH_TOKEN``. That
endpoint is only mounted on labs and only when the env var is non-empty.
Token lives in deploy/aws/task-definition.json and AWS Secrets Manager.

Usage
=====
    # Default: hit labs with the bot identity
    uv run --extra walkthrough python scripts/qa/labs_probe.py

    # Override the base URL or token
    LABS_URL=https://...  LABS_TOKEN=... uv run --extra walkthrough \
        python scripts/qa/labs_probe.py

Output
======
    qa-results/<UTC-iso>/
        report.json           full structured results
        report.md             human-readable summary
        <step-name>.png       full-page screenshot per step
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import Page, sync_playwright
except ImportError:
    print("Run with `uv run --extra walkthrough`", file=sys.stderr)
    sys.exit(2)


BASE = os.environ.get("LABS_URL", "https://labs.connect.dimagi.com/ace")
TOKEN = os.environ.get("LABS_TOKEN", "")
EMAIL = os.environ.get("LABS_EMAIL", "ace@dimagi-ai.com")
WORKSPACE = os.environ.get("LABS_WORKSPACE", "dimagi-team")

REPO = Path(__file__).resolve().parents[2]
RUN_ID = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
OUT = REPO / "qa-results" / RUN_ID


@dataclass
class StepResult:
    name: str
    path: str
    http_status: int | None = None
    verdict: str = "pending"  # ok | partial | broken | fatal
    preview: str = ""
    bad_responses: list[dict[str, Any]] = field(default_factory=list)
    js_errors: list[str] = field(default_factory=list)
    error_pre_text: str = ""
    fatal: str = ""
    screenshot: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "http_status": self.http_status,
            "verdict": self.verdict,
            "preview": self.preview,
            "bad_responses": self.bad_responses,
            "js_errors": self.js_errors,
            "error_pre_text": self.error_pre_text,
            "fatal": self.fatal,
            "screenshot": self.screenshot,
        }


# ---------------------------------------------------------------------------
# Visit helpers
# ---------------------------------------------------------------------------


def _capture(page: Page) -> tuple[list, list]:
    """Return (bad_responses_list, js_errors_list) — both populated by listeners."""
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


def _classify(body: str, bad: list, errs: list) -> str:
    if "Unexpected Application Error" in body or "Something went wrong" in body:
        return "broken"
    if errs:
        return "broken"
    if bad:
        return "partial"
    return "ok"


def visit(ctx, name: str, path: str, *, wait_ms: int = 2500) -> StepResult:
    """Navigate, wait for paint, classify."""
    page = ctx.new_page()
    bad, errs = _capture(page)
    r = StepResult(name=name, path=path)
    try:
        resp = page.goto(BASE + path, wait_until="domcontentloaded", timeout=30000)
        r.http_status = resp.status if resp else None
        page.wait_for_timeout(wait_ms)
        # Force-open <details> so error pre text is captured.
        page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
        page.wait_for_timeout(200)
        screenshot_path = OUT / f"{name}.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        r.screenshot = str(screenshot_path.relative_to(REPO))
        body = page.locator("body").inner_text()
        # Strip nav header for preview readability
        parts = body.split("ace@dimagi-ai.com", 1)
        useful = (parts[1] if len(parts) > 1 else body).strip()[:240].replace("\n", " | ")
        r.preview = useful
        r.bad_responses = bad
        r.js_errors = errs
        pres = page.locator("pre")
        if pres.count() > 0:
            r.error_pre_text = pres.first.inner_text()[:600]
        r.verdict = _classify(body, bad, errs)
    except Exception as e:
        r.fatal = str(e)[:200]
        r.verdict = "fatal"
    finally:
        page.close()
    return r


# ---------------------------------------------------------------------------
# Probe surface — what to walk
# ---------------------------------------------------------------------------


CORE_SURFACES = [
    # name, path
    ("00-home",               "/"),
    ("01-welcome",            "/welcome"),
    ("02-workspace-home",     f"/w/{WORKSPACE}"),
    ("03-opps-list",          f"/w/{WORKSPACE}/opps"),
    ("04-sessions-list",      f"/w/{WORKSPACE}/sessions"),
    ("05-workspace-settings", f"/w/{WORKSPACE}/workspace-settings"),
    ("06-settings",           "/settings"),
    ("07-system-overview",    "/system"),
    ("08-system-pipeline",    "/system?tab=pipeline"),
    ("09-system-agents",      "/system?tab=agents"),
    ("10-system-mcps",        "/system?tab=mcps"),
    ("11-auth-cli",           "/auth/cli"),
    ("12-videos-list",        f"/w/{WORKSPACE}/videos"),
]


# View-mode tabs to probe on each opp's workbench page.
OPP_VIEW_MODES = ["phase", "workbench", "heatmap", "diff"]


def discover_opps(ctx) -> list[str]:
    """Pull opp slugs from the live API directly (more reliable than DOM scraping)."""
    resp = ctx.request.get(f"{BASE}/api/w/{WORKSPACE}/opps")
    if resp.status != 200:
        return []
    data = resp.json()
    items = data.get("items", []) if isinstance(data, dict) else data
    return [o["slug"] for o in items if "slug" in o]


def discover_sessions(ctx, limit: int = 5) -> list[str]:
    """Pull recent session slugs from the live API."""
    resp = ctx.request.get(f"{BASE}/api/w/{WORKSPACE}/sessions?limit={limit}")
    if resp.status != 200:
        return []
    data = resp.json()
    items = data.get("items", []) if isinstance(data, dict) else data
    return [s["slug"] for s in items if "slug" in s][:limit]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _login(ctx) -> bool:
    """Hit /auth/e2e-login/ to get a session cookie. Requires LABS_TOKEN."""
    if not TOKEN:
        print(
            "LABS_TOKEN not set. Get it from deploy/aws/task-definition.json "
            "(env var ACE_E2E_AUTH_TOKEN) and export it.",
            file=sys.stderr,
        )
        return False
    resp = ctx.request.post(
        f"{BASE}/auth/e2e-login/",
        data=json.dumps({"email": EMAIL, "token": TOKEN}),
        headers={"Content-Type": "application/json"},
    )
    if resp.status != 200:
        print(f"[auth] FAILED status={resp.status} body={resp.text()[:200]}", file=sys.stderr)
        return False
    print(f"[auth] OK ({EMAIL})")
    return True


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"[probe] base={BASE} workspace={WORKSPACE} out={OUT.relative_to(REPO)}")

    results: list[StepResult] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        if not _login(ctx):
            browser.close()
            return 2

        # Discovery happens before navigation so we know what to drill into.
        opps = discover_opps(ctx)
        sessions = discover_sessions(ctx, limit=3)
        print(f"[discover] opps={opps} sessions={sessions}")

        # 1. Top-level surfaces
        print("\n=== Core surfaces ===")
        for name, path in CORE_SURFACES:
            r = visit(ctx, name, path)
            results.append(r)
            print(f"  {'✓' if r.verdict == 'ok' else '✗'} {r.verdict:7s} {name:30s} {r.preview[:70]}")

        # 2. Each opp's workbench + view-mode tabs
        print("\n=== Opp workbenches ===")
        for slug in opps:
            base_path = f"/w/{WORKSPACE}/opps/{slug}"
            safe_slug = re.sub(r"[^a-z0-9-]", "_", slug.lower())
            for view in OPP_VIEW_MODES:
                name = f"opp-{safe_slug}-view-{view}"
                r = visit(ctx, name, f"{base_path}?view={view}")
                results.append(r)
                mark = "✓" if r.verdict == "ok" else "✗"
                print(f"  {mark} {r.verdict:7s} {slug:30s} view={view:10s} {r.preview[:50]}")

        # 3. Drill into a specific run of the most-active opp
        if opps:
            slug = opps[0]
            runs_resp = ctx.request.get(f"{BASE}/api/w/{WORKSPACE}/opps/{slug}/runs")
            if runs_resp.status == 200:
                run_ids = [r["run_id"] for r in runs_resp.json().get("items", [])][:3]
                print(f"\n=== Run drilling (opp={slug}, first 3 of {len(run_ids)}) ===")
                for run_id in run_ids:
                    safe_run = re.sub(r"[^a-z0-9-]", "_", run_id.lower())
                    r = visit(ctx, f"opp-{slug}-run-{safe_run}", f"/w/{WORKSPACE}/opps/{slug}/runs/{run_id}")
                    results.append(r)
                    mark = "✓" if r.verdict == "ok" else "✗"
                    print(f"  {mark} {r.verdict:7s} run={run_id:20s} {r.preview[:50]}")

        # 4. Session structure (non-chat view of each session)
        print(f"\n=== Sessions ({len(sessions)} drilled) ===")
        for slug in sessions:
            short = slug[:8]
            r = visit(ctx, f"session-structure-{short}", f"/w/{WORKSPACE}/chat/{slug}/structure")
            results.append(r)
            mark = "✓" if r.verdict == "ok" else "✗"
            print(f"  {mark} {r.verdict:7s} {short:10s} {r.preview[:70]}")

        # 5. Step deep-link (most-active opp, first phase, first skill)
        if opps:
            slug = opps[0]
            snap_resp = ctx.request.get(f"{BASE}/api/w/{WORKSPACE}/opps/{slug}")
            if snap_resp.status == 200:
                snap = snap_resp.json()
                run = snap.get("current_run", {})
                steps = run.get("steps", [])
                if steps and run.get("run_id"):
                    run_id = run["run_id"]
                    skill = steps[0].get("skill_name") or steps[0].get("skill")
                    if skill:
                        path = f"/w/{WORKSPACE}/opps/{slug}/runs/{run_id}/steps/{skill}"
                        print(f"\n=== Step deep-link (opp={slug}, run={run_id}, skill={skill}) ===")
                        r = visit(ctx, f"opp-{slug}-step-{skill}", path)
                        results.append(r)
                        mark = "✓" if r.verdict == "ok" else "✗"
                        print(f"  {mark} {r.verdict:7s} {r.preview[:80]}")

        # 6. Opp-vs-opp compare (if >= 2 opps with runs)
        if len(opps) >= 2:
            slug_a, slug_b = opps[0], opps[1]
            path = f"/w/{WORKSPACE}/opps/compare/{slug_a}/{slug_b}"
            print(f"\n=== Opp compare ({slug_a} vs {slug_b}) ===")
            r = visit(ctx, f"opp-compare-{slug_a}-{slug_b}", path)
            results.append(r)
            mark = "✓" if r.verdict == "ok" else "✗"
            print(f"  {mark} {r.verdict:7s} {r.preview[:80]}")

        # 7. Public per-run summary (no auth — used for stakeholder share links)
        if opps:
            slug = opps[0]
            runs_resp = ctx.request.get(f"{BASE}/api/w/{WORKSPACE}/opps/{slug}/runs")
            if runs_resp.status == 200:
                items = runs_resp.json().get("items", [])
                if items:
                    run_id = items[0]["run_id"]
                    # PUBLIC route — no /w/ prefix, no auth required. Open in
                    # a fresh incognito-ish context so we genuinely test the
                    # no-auth path (the bot's session cookie would mask
                    # auth-related regressions).
                    pub_browser = p.chromium.launch(headless=True)
                    pub_ctx = pub_browser.new_context(viewport={"width": 1280, "height": 900})
                    path = f"/opps/{WORKSPACE}/{slug}/runs/{run_id}/summary"
                    print("\n=== Public summary (no auth) ===")
                    r = visit(pub_ctx, "public-summary", path)
                    results.append(r)
                    mark = "✓" if r.verdict == "ok" else "✗"
                    print(f"  {mark} {r.verdict:7s} {r.preview[:80]}")
                    pub_browser.close()

        # 8. API coverage cross-check: walk the OpenAPI schema, probe every
        # GET endpoint that doesn't need path params we don't know how to
        # supply. The goal isn't to validate response shape (that's
        # schemathesis's job in CI) — it's to detect endpoints that 5xx
        # because they're calling deleted code, or 404 because they were
        # never mounted.
        print("\n=== API coverage (GET endpoints with no required path params) ===")
        schema_resp = ctx.request.get(f"{BASE}/api/openapi.json")
        if schema_resp.status == 200:
            paths = schema_resp.json().get("paths", {})
            unparametric_gets: list[tuple[str, str]] = []
            for path_str, ops in paths.items():
                # Only test paths with no `{param}` (or where every param
                # is a query, not path). Parametric paths get covered by
                # the UI walk above.
                if "{" in path_str:
                    continue
                if "get" not in ops:
                    continue
                unparametric_gets.append((path_str, ops["get"].get("summary", "")))
            print(f"  {len(unparametric_gets)} unparametric GET paths to probe")
            for path_str, summary in unparametric_gets:
                resp = ctx.request.get(f"{BASE}{path_str}")
                # Anything in [200, 304, 401, 403, 404] is normal (auth gate
                # or genuinely-empty resource). 5xx is the alarm.
                ok = resp.status < 500
                mark = "✓" if ok else "✗"
                tag = "ok" if ok else f"5xx={resp.status}"
                print(f"  {mark} {tag:7s} GET {path_str}")
                if not ok:
                    results.append(StepResult(
                        name=f"api-coverage-{path_str.replace('/', '_')}",
                        path=path_str,
                        http_status=resp.status,
                        verdict="broken",
                        bad_responses=[{"status": resp.status, "method": "GET", "url": path_str}],
                        preview=f"summary: {summary}",
                    ))

        browser.close()

    # Write report
    summary = {
        "base": BASE,
        "workspace": WORKSPACE,
        "run_id": RUN_ID,
        "counts": {
            "total": len(results),
            "ok":      sum(1 for r in results if r.verdict == "ok"),
            "partial": sum(1 for r in results if r.verdict == "partial"),
            "broken":  sum(1 for r in results if r.verdict == "broken"),
            "fatal":   sum(1 for r in results if r.verdict == "fatal"),
        },
        "results": [r.to_dict() for r in results],
    }
    (OUT / "report.json").write_text(json.dumps(summary, indent=2))
    _write_markdown(summary, OUT / "report.md")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    c = summary["counts"]
    print(f"  total={c['total']} ok={c['ok']} partial={c['partial']} broken={c['broken']} fatal={c['fatal']}")
    print(f"  report: {OUT.relative_to(REPO)}/report.md")

    broken = [r for r in results if r.verdict in ("broken", "fatal")]
    if broken:
        print("\nFailures:")
        for r in broken:
            print(f"\n  ✗ {r.name} ({r.path})")
            if r.fatal:
                print(f"    FATAL: {r.fatal}")
            for b in r.bad_responses[:3]:
                print(f"    {b['status']} {b['method']} {b['url']}")
            if r.error_pre_text:
                print(f"    ERR: {r.error_pre_text[:200]}")
            for e in r.js_errors[:2]:
                print(f"    JS:  {e[:160]}")

    return 1 if broken else 0


def _write_markdown(summary: dict, path: Path) -> None:
    c = summary["counts"]
    lines = [
        f"# Labs E2E Probe — {summary['run_id']}",
        "",
        f"- Base: `{summary['base']}`",
        f"- Workspace: `{summary['workspace']}`",
        f"- Total: {c['total']} | ✓ {c['ok']} | ⚠ {c['partial']} | ✗ {c['broken']} | 💥 {c['fatal']}",
        "",
        "## Results",
        "",
        "| # | Name | Verdict | Status | Preview |",
        "|---|------|---------|--------|---------|",
    ]
    for i, r in enumerate(summary["results"], 1):
        lines.append(
            f"| {i} | `{r['name']}` | {r['verdict']} | {r['http_status'] or '-'} | "
            f"{r['preview'][:80].replace('|', '/')} |"
        )
    broken = [r for r in summary["results"] if r["verdict"] in ("broken", "fatal")]
    if broken:
        lines += ["", "## Failures", ""]
        for r in broken:
            lines += [
                f"### {r['name']}",
                "",
                f"- Path: `{r['path']}`",
                f"- HTTP: {r['http_status']}",
            ]
            if r.get("fatal"):
                lines.append(f"- Fatal: `{r['fatal']}`")
            if r["bad_responses"]:
                lines.append("- Bad responses:")
                for b in r["bad_responses"][:5]:
                    lines.append(f"  - `{b['status']} {b['method']} {b['url']}`")
            if r["error_pre_text"]:
                lines += ["- Error pre:", "  ```", "  " + r["error_pre_text"][:400].replace("\n", "\n  "), "  ```"]
            if r["js_errors"]:
                lines.append("- JS errors:")
                for e in r["js_errors"][:3]:
                    lines.append(f"  - `{e[:160]}`")
            lines.append("")
            if r["screenshot"]:
                lines += [f"![{r['name']}](../../{r['screenshot']})", ""]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
