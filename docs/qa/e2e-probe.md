# Labs E2E Probe

A re-runnable Playwright probe that walks every UI surface on a deployed
ace-web, captures HTTP/JS errors + a full-page screenshot per step, and
writes a structured report.

Lives at `scripts/qa/labs_probe.py`. Re-run after every deploy.

## Why scripted, not LLM-driven

Two viable designs were considered:

| Approach | Pros | Cons |
|---|---|---|
| **Scripted Playwright** (chosen) | Deterministic, cheap, fast (~1 min for 30+ steps), CI-runnable, diffable JSON output | Misses pure-aesthetic regressions ("colour is off") |
| **LLM-driven walk** | Catches semantic issues ("this label is misleading") | Slow, costs $ per run, non-deterministic, hard to track regressions over time |

Verdict: scripted for the load-bearing claims (page loaded, no console
errors, no error-UI overlays, no 4xx/5xx), with explicit screenshots so a
human or LLM can dive into specifics on demand. The probe is the
*forgetting-to-eyeball* fix, not the eyeball replacement.

## What it probes

- **Core surfaces** — home, welcome, workspace home, opps/sessions/workspace-settings/settings/system/auth-cli/videos.
- **Each opp** — workbench page, plus every view-mode tab (`phase`,
  `workbench`, `heatmap`, `diff`).
- **Runs** — picks the most-active opp and drills into 3 specific runs.
- **Step deep-link** — opens `/w/<ws>/opps/<slug>/runs/<runId>/steps/<skill>` for one real step.
- **Opp compare** — opens `/w/<ws>/opps/compare/<a>/<b>` between the first two opps.
- **Public summary page** (no auth) — opens the stakeholder-facing per-run summary at `/opps/<ws>/<slug>/runs/<runId>/summary` in a fresh browser context (no cookies) so genuinely-public access is tested.
- **Sessions** — opens 3 recent sessions' structure tab (the non-chat view).
- **API coverage** — walks `/api/openapi.json` and probes every unparametric GET endpoint. Catches dead endpoints (5xx) and "frontend calls a path that was deleted in backend cleanup" regressions.

**Skipped intentionally** — chat interface (user request), generation flows (new opp / fork), `/invite/<token>` and `/share/<token>` (need real tokens — add a fixture if you want them covered).

For each step:
- HTTP status of the navigation
- 4xx/5xx responses captured from API calls
- Console errors + page errors from the browser
- DOM scan for `Unexpected Application Error` / `Something went wrong`
- Full-page screenshot
- First `<pre>` text inside any open `<details>` (captures inline error stacks)

Verdict per step:
- **ok** — clean
- **partial** — bad HTTP responses observed but no error UI
- **broken** — error UI detected OR JS errors
- **fatal** — navigation timed out / crashed

## How to run

Prereqs:
- `uv` (project's package manager)
- Playwright browsers installed once: `uv run --extra walkthrough playwright install chromium`
- `LABS_TOKEN` — a Bearer PAT. Mint one via `/ace:ace-web-pat-mint`
  (gh-style loopback browser flow, one-time per machine), then export
  the raw token. See `apps/auth/cli_authorize_views.py` for the
  server side of the mint flow.

```bash
export LABS_TOKEN=...
uv run --extra walkthrough python scripts/qa/labs_probe.py
```

Run against a different target:

```bash
LABS_URL=https://staging.example.com/ace LABS_WORKSPACE=my-team \
  uv run --extra walkthrough python scripts/qa/labs_probe.py
```

## Output

```
qa-results/<UTC-iso>/
    report.json       structured results (counts, per-step verdict, raw error data)
    report.md         human-readable summary with screenshot links
    <step-name>.png   one per probe step
```

The `qa-results/` directory is gitignored. Each run lands in a new
timestamped subdir; nothing is overwritten.

Exit code is 0 when every step is `ok` or `partial`, 1 when any step is
`broken` or `fatal`. Wire to CI when ready.

## Extending the probe

To add a new surface, edit `CORE_SURFACES` in `scripts/qa/labs_probe.py`:

```python
CORE_SURFACES = [
    ...,
    ("12-my-new-page", "/w/{workspace}/my-new-page"),
]
```

For new dynamic drilling (e.g., "expand each member in workspace
settings"), follow the pattern in `main()`:

1. Discover IDs via the live API (`ctx.request.get(...)`).
2. For each ID, call `visit(ctx, name, path)` and append the result.

Each `visit()` call is ~3 seconds including the screenshot, so a probe
of 30-40 steps takes about 90 seconds.

## Reading a failure report

A `broken` step's row in `report.md` includes:

- The exact path that failed
- Any bad responses (`401`, `404`, `500` etc.)
- The inline error stack from React's error boundary (if shown)
- JS errors caught from the browser console
- A link to the full-page screenshot

Most regressions land here as one of three patterns:

1. **Schema/shape mismatch.** Frontend reads `opp.display_name` but
   backend sends `opp.title`. Shows up as a JS error like
   `Cannot read properties of undefined`. Fix: align the backend dict.
2. **Missing endpoint.** A frontend call hits a 404 because the v2
   migration dropped a path. Shows up as `404 GET /api/...` in the row.
3. **Auth/CSRF cookie misconfig.** Every page redirects to `/auth/login`.
   Shows up as either all-broken or a single 401 from `GET /api/auth/me`.

## Known clutter / unused surfaces

The probe doesn't enforce opinions, but the things below regularly come
back ok-but-empty and may be candidates for removal:

- `?view=heatmap` and `?view=diff` on the opp workbench — rarely
  populated, no obvious user trigger.
- `?view=story` (Storyboard) — present in the tab strip but I'm not
  sure anyone clicks it.
- The two opps with empty Drive folders (`Malaria ITN FGD`,
  `cosmetics-fgd-pilot`) — show up in the list but 404 on click.
  Either filter them server-side or delete the folders.
- `/health` is a public route that exposes infra status — fine for
  ops, but probably shouldn't be reachable via the in-app nav.

These are observations, not action items. Tally them across a few runs
before pruning.
