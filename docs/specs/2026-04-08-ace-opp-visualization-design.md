# ACE Opportunity Visualization — Design Spec

**Date:** 2026-04-08
**Status:** Draft — awaiting user sign-off before writing-plans
**Scope:** A new `apps/opps/` module in ace-web that reads ACE opportunity state
live from Google Drive and renders a dense, interactive Workbench view of every
skill's output, with first-class integration into ace-web's own chat harness for
skill improvement.

---

## 1. Overview

ACE runs a 19-skill lifecycle against a Connect opportunity and writes everything
it produces into a Google Drive folder. Today there is no UI that lets the team
see what ACE produced, compare runs of the same IDD across skill iterations, or
jump from a bad output into a chat to fix the underlying skill. This spec closes
that gap.

The visualization is **the Workbench**: a three-pane view inside ace-web that
shows (left) all opportunities, (center) all 19 skills of the selected run in a
dense scannable list with inline output previews, and (right) a detail pane for
the clicked step with artifact bodies, judge verdicts, gate history, linked
chats, and a single hero CTA — "Discuss in chat" — that creates a new ace-web
session pre-seeded with the step's context so the team can iterate on the output
and push a SKILL.md improvement to GitHub from the chat.

Google Drive is the source of truth. ace-web reads through to Drive on every
request using the logged-in user's OAuth credentials. No Postgres mirror, no
background sync, no event push from the ACE plugin. Slowness is acceptable. The
primary design artifact is therefore not a database schema — it is a clean,
portable, git-friendly Drive folder layout that both ace-web and the ACE plugin
commit to.

## 2. Goals

1. **See every skill's output at a glance.** All 19 skills of a run visible in a
   single dense list with inline per-skill previews, judge scores, judge-delta
   vs the prior run, gate badges, and click-to-drill-in behavior.
2. **Close the improvement loop inside ace-web.** One click from any step's
   output into a chat session seeded with the IDD, the artifact bodies, the
   judge verdict, and a preamble telling Claude which SKILL.md to consider
   editing. The chat session handles the actual edit + GitHub push.
3. **Multi-run is first-class.** Multiple runs per IDD exist in the Drive
   folder layout and the URL structure from day one. The UI for comparing
   runs can be light — but the shape must support it without rework.
4. **Drive is the store; the format is the spec.** A well-defined, portable
   folder layout that a human or another tool can read without ace-web. Any
   future migration to a Postgres snapshot is a caching decision, not a model
   change.
5. **Respect existing Dimagi Drive permissions.** Users see exactly the opps
   their own Google identity has Drive access to. No shared service account,
   no privilege escalation.

## 3. Users

Internal Dimagi team members authenticated via django-allauth + Connect
OAuth (the ace-web identity flow that replaces the prior IAP model). Scope is
`@dimagi.com` emails. No external users in scope. Anonymous share links are
explicitly out of scope for v1 — the team already shares Drive folders directly
when they need to bring someone in.

## 4. Surfaces

All URLs live under `/opps/` inside Django and are served externally as
`/ace/opps/...` via `FORCE_SCRIPT_NAME=/ace` (the scout-pattern tenant prefix).

| URL | Role |
|---|---|
| `/opps` | Opportunity list — the left pane as a standalone page for deep-links |
| `/opps/<opp-slug>` | Workbench view on the opp's **current run** |
| `/opps/<opp-slug>/runs/<run-id>` | Workbench view scoped to a specific run |
| `/opps/<opp-slug>/runs/<run-id>/steps/<skill>` | Workbench view with a step's detail pane pre-opened |
| `/opps/<opp-slug>/compare?from=<run-a>&to=<run-b>` | Lightweight run-to-run comparison page |
| `/auth/drive/start` / `/auth/drive/callback` | Google OAuth second-flow for Drive scope |

### 4.1 The Workbench layout

Three panes, locked in via visual mockup review (`.superpowers/brainstorm/`).

**Left pane — Opp list (180px wide):**
- Filter input
- List of opportunities the logged-in user has Drive access to, one row per opp
- Each row: name, optional run-version badge (`v2`, `v3`…), one-line status
- Click to navigate to the opp's workbench

**Center pane — Dense 19-skill list:**
- Header: opp name, current phase, mode (auto / review / dry-run), run switcher
  (dropdown of all runs for this opp), "compare to v1" link
- Four phase-grouped sections (App Building, Connect Setup, LLO Management,
  Closeout) with subtle dividers
- One row per skill (19 rows), with row anatomy:
  `[status dot] [skill name] [judge-bar] [score] [Δ vs prior run] [gate badge] [inline artifact preview]`
- Inline artifact preview is the killer content: a one-line string built by a
  per-skill extractor, e.g. `"📄 idd.md — 'Reduce malaria infant mortality in
  northern Mozambique via monthly FLW-administered RDT screening…'"`, or `"🧪
  38/40 pass · 2 failures in deliver case-create flow"`
- Recurring skills (`timeline-monitor`, `flw-data-review`) collapse to one row
  with an "N runs" disclosure
- Clicking a row loads the right pane

**Right pane — Step detail (300px wide):**
- Selected skill name + status
- **Primary CTA: "💬 Discuss in chat"** — gradient button, opens a new ace-web
  session seeded with IDD + artifact bodies + judge rationale + a preamble
  telling Claude it can propose a SKILL.md edit and push it
- Artifact preview block (first ~10 lines of the primary artifact) + "open full
  markdown →" link that deep-links into the Drive web view
- Judge verdict card with score, criteria breakdown, full rationale
- Gate history (approvals/rejections with who + when)
- Linked chats list (prior ace-web `Session` rows linked to this step)
- "vs Run v1" mini-panel with one-click side-by-side

### 4.2 Run switcher and comparison

- Run switcher: dropdown in the top bar, options are all runs for this opp
  ordered newest-first, with the current run marked. Each entry shows a
  display label (`v3`, `v2`, `v1`, derived from run ordinal) plus the
  canonical `run_id` and start date; the label is UI-only — the URL and all
  API calls use `run_id`
- "compare to v1" next to the switcher → navigates to the compare page
- Compare page: two-column layout with the same 19-skill list on each side,
  score deltas highlighted inline. No token-level diffing. Clicking a pair of
  rows opens side-by-side artifact previews
- Intentionally thin: not-critical UI per user guidance; the format and data
  model support full diffing if we want to invest in it later

## 5. Auth

Two separate OAuth flows, on top of each other:

### 5.1 Identity: django-allauth + Connect OAuth
Existing / in-flight ace-web auth. Establishes who the user is and gates all of
ace-web behind `@dimagi.com` membership. No change from the Phase 2 plan.

### 5.2 Drive access: secondary Google OAuth
The ace-web `User` model gains two fields: `drive_token_cache` (encrypted
JSONField holding `{access_token, refresh_token, token_uri, scopes}`) and
`drive_token_refreshed_at` (DateTimeField, nullable). A single migration.

On first visit to `/opps` (or any API call under `/api/opps/*` that needs
Drive access), middleware checks whether the logged-in `User` has a valid
Drive token. If not, page requests redirect to `/auth/drive/start`; API
requests return a 401 with a `{"reconnect_url": "/auth/drive/start"}` body
that the frontend uses to kick off the redirect.

- `GET /auth/drive/start` — builds the Google OAuth consent URL (scopes:
  `openid email profile https://www.googleapis.com/auth/drive.readonly
  https://www.googleapis.com/auth/spreadsheets.readonly`) and redirects
- `GET /auth/drive/callback?code=...` — exchanges the code, stores `{access_token,
  refresh_token, token_uri, scopes}` encrypted on `User.drive_token_cache`, then
  redirects back to `/opps`

Pattern copied verbatim from `../connect-search/backend/app/core/{drive,auth}.py`
+ `app/api/auth.py`, translated from FastAPI to Django views. `DriveClient` ABC
+ `GoogleDriveClient` impl copy across as-is.

Token encryption via Fernet; key loaded from AWS Secrets Manager / SSM Parameter
Store at boot (the scout-pattern tenant's standard place for runtime secrets).

Google OAuth client ID + secret live in the same connect-search OAuth project
unless there's a reason to mint a new one. Callback URIs:
- dev: `http://localhost:8000/auth/drive/callback`
- prod: `https://labs.connect.dimagi.com/ace/auth/drive/callback`

### 5.3 Access token refresh
On every Drive call, the `DriveClient` wrapper checks whether the access token
has expired (leaving a 60s buffer). If so, hits the token endpoint with the
refresh token, updates `User.drive_token_cache`, stamps
`User.drive_token_refreshed_at`, and retries. If the refresh itself fails, the
user is redirected to `/auth/drive/start` with a "please reconnect" banner.

## 6. Drive folder format (the primary design artifact)

This is where the bulk of the value lives. ace-web and the ACE plugin co-own
this format. Humans can read it. Git diffs it cleanly. A future tool can
consume it without ace-web.

```
ACE/                                      # Drive root (already convention)
  <opp-slug>/                             # e.g. "malaria-pilot"
    opp.yaml                              # static metadata (see 6.1)
    idd.md                                # canonical IDD — the "thesis"
    runs/                                 # all runs of the above IDD, sorted by id
      <run-id>/                           # e.g. "2026-04-01-001"
        run.yaml                          # run-level state (see 6.2)
        events.jsonl                      # append-only timeline (see 6.3)
        steps/
          01-idea-to-idd/
            step.yaml                     # per-step state (see 6.4)
            output/
              idd.md                      # the step's canonical output(s)
            judge.yaml                    # optional — for LLM-judged skills
            gates.jsonl                   # optional — for gate steps (append-only)
          02-idd-to-learn-app/
            step.yaml
            output/
              learn-app-brief.md
            judge.yaml
          03-idd-to-deliver-app/
            ...
          04-app-deploy/
            step.yaml
            output/
              deploy-summary.md
            gates.jsonl
          05-app-test/
            step.yaml
            output/
              test-plan.md
              test-results.yaml
              bug-list.md
            judge.yaml
          06-training-materials/
            step.yaml
            output/
              llo-manager-guide.md
              flw-training-guide.md
              quick-reference.md
              faq.md
            judge.yaml
          07-connect-program-setup/
            ...
          ...
          19-cycle-grade/
            step.yaml
            output/
              grade-report.md
            judge.yaml
```

### 6.1 `opp.yaml`
```yaml
slug: malaria-pilot
display_name: Malaria Pilot — Northern Mozambique
created_at: 2026-03-15T09:00:00Z
created_by: neal@dimagi.com
labels: [malaria, mozambique, q2-2026]
current_run_id: 2026-04-06-002      # pointer to the run considered "current"
```

Intentionally static. The dynamic state lives under `runs/<run-id>/run.yaml`.
`current_run_id` is a pointer so the opp landing page knows which run to show
by default; the UI always lets the user pick a different run.

### 6.2 `run.yaml`
```yaml
run_id: 2026-04-06-002
mode: review                         # auto | review | dry-run | sandbox
status: running                      # running | blocked | complete | failed | abandoned
started_at: 2026-04-06T10:12:00Z
completed_at: null
current_phase: app-building
current_step: app-deploy
skill_versions:                      # git commit SHAs or version tags of SKILL.md files used
  idea-to-idd: 4f2b8c1
  idd-to-learn-app: 4f2b8c1
  idd-to-deliver-app: 4f2b8c1
  app-deploy: 8a91f22                # note: different version than the rest
  app-test: 4f2b8c1
  ...
notes: |
  Re-run after editing app-deploy SKILL.md to handle Nova packaging bug.
```

The `skill_versions` map is the mechanism that lets run-to-run comparison
attribute deltas to specific skill edits. If a cell changes between runs, the
UI can surface "which skill was updated."

### 6.3 `events.jsonl`
Append-only timeline of everything the ACE plugin emits during a run. One JSON
object per line. Allows future scrubbable timeline UIs without format change.
```jsonl
{"ts":"2026-04-06T10:12:00Z","kind":"run.started","payload":{"mode":"review"}}
{"ts":"2026-04-06T10:12:03Z","kind":"step.started","step":"idea-to-idd"}
{"ts":"2026-04-06T10:14:22Z","kind":"artifact.written","step":"idea-to-idd","payload":{"path":"output/idd.md"}}
{"ts":"2026-04-06T10:14:25Z","kind":"judge.rendered","step":"idea-to-idd","payload":{"score":9.2,"passed":true}}
{"ts":"2026-04-06T10:14:25Z","kind":"gate.pending","step":"idea-to-idd"}
{"ts":"2026-04-06T10:16:02Z","kind":"gate.approved","step":"idea-to-idd","payload":{"by":"neal@dimagi.com"}}
{"ts":"2026-04-06T10:16:03Z","kind":"step.completed","step":"idea-to-idd"}
```

### 6.4 `step.yaml`
```yaml
skill_name: app-deploy
phase: app-building
ordinal: 4
status: gate-pending                 # pending | running | complete | judge-fail | gate-pending | gate-rejected | error | skipped
started_at: 2026-04-06T10:34:00Z
completed_at: null
error: null
# Optional: stats the skill wants to surface on the row preview. If absent,
# ace-web's per-skill extractor reads the output files instead.
preview_stats:
  apps_packaged: 2
  target_domain: crispr-connect
```

### 6.5 `judge.yaml` (optional)
```yaml
score: 9.2                           # 0-10
passed: true
evaluated_at: 2026-04-06T10:14:25Z
criteria:                            # per-criterion breakdown
  completeness: 9.5
  specificity: 9.0
  feasibility: 8.5
  measurability: 10.0
rationale: |
  The IDD is comprehensive, specifying the malaria intervention with concrete
  FLW protocols, RDT administration procedures, and measurable success metrics
  tied to the number of children screened and referred…
```

### 6.6 `gates.jsonl` (optional, append-only)
```jsonl
{"ts":"2026-04-06T10:14:25Z","decision":"pending","payload":{"reason":"awaiting review"}}
{"ts":"2026-04-06T10:16:02Z","decision":"approved","decided_by":"neal@dimagi.com","note":"looks good"}
```

### 6.7 Per-skill `preview_text` extraction
ace-web has a tiny per-skill extractor registry (`apps/opps/previews.py`) that
turns the primary artifact body into the one-line inline preview shown in the
center pane. One function per skill. Falls back to a generic "N artifacts" if a
skill is unknown. Extractors prefer `step.yaml#preview_stats` when present to
avoid re-reading bodies.

### 6.8 Migration / backward compatibility
The ACE plugin today writes a flat `ACE/<opp-slug>/` with `state.yaml` +
`idd.md` + artifact subfolders. ace-web's sync layer MUST tolerate the current
flat layout as "a single implicit run with id `r1`" so the team can use the
Workbench before the ACE plugin adopts the new format. When the plugin catches
up, the format above becomes canonical and the flat-layout fallback can be
retired.

Adopting this format is a coordination point with the ACE plugin maintainers.
This spec is the proposal; landing it requires a companion PR in the `ace`
repo that updates the plugin's write path.

## 7. Data flow

Read-through from Drive. No cache beyond per-request coalescing.

### 7.1 Opp list endpoint
```
GET /api/opps
→ list every folder under ACE/ that contains either `opp.yaml` or a `state.yaml`
  + `idd.md` (legacy heuristic), return minimal card data per opp
```

### 7.2 Workbench endpoint
```
GET /api/opps/<slug>?run_id=<optional>
→ list the opp's runs directory (or infer a single run from flat layout)
→ resolve `run_id` (default: opp.yaml#current_run_id or latest by name)
→ read run.yaml + step.yaml for every step
→ read judge.yaml where present
→ read the first few bytes of each output file to build preview_text
→ return the full workbench payload as JSON
```

This is the slow path — potentially N Drive reads per view. Acceptable per the
"Drive is SoT, slowness is OK" directive. Implementation must coalesce
duplicate reads within a request and batch-fetch folder contents where the
Google Drive API allows.

### 7.3 Step detail endpoint
```
GET /api/opps/<slug>/runs/<run-id>/steps/<skill>
→ full step.yaml
→ full judge.yaml (all historical judges, if multiple — see 7.6)
→ full gates.jsonl
→ list output/ files with metadata
→ first ~200 lines of the primary output artifact, plus the Drive web link
→ list `Session` rows in Postgres where `(opp_slug, opp_run_id, opp_step_skill)` match
```

### 7.4 Artifact body endpoint
```
GET /api/opps/<slug>/runs/<run-id>/steps/<skill>/artifacts/<name>
→ streams the raw Drive body back to the browser
```

Used for the "open full markdown →" link and for deeper artifact viewing. The
browser renders markdown and JSON inline; unknown types get a download link and
a Drive web-view link.

### 7.5 Compare endpoint
```
GET /api/opps/<slug>/compare?from=<run-a>&to=<run-b>
→ returns both runs' workbench payloads in one response
```

Frontend renders them side-by-side and computes per-row deltas in JavaScript.
No server-side diffing.

### 7.6 Judge history
If a step has been re-judged (e.g. the team edited the judge criteria and
re-ran ACE against the same outputs), multiple `judge.yaml` files can exist as
`judge.yaml`, `judge-002.yaml`, `judge-003.yaml`. The latest is the source for
the row score; older ones show up in the step detail pane under a "judge
history" disclosure. If the plugin only writes a single `judge.yaml`,
everything still works — history is empty.

## 8. Chat integration — the killer feature

```
POST /api/opps/<slug>/runs/<run-id>/steps/<skill>/discuss
Body: {}
→ creates a new ace-web Session
→ sets session.opp_slug, session.opp_run_id, session.opp_step_skill, session.idd_ref
→ posts a seed system message containing:
    - IDD excerpt (up to 2k tokens)
    - This step's output bodies (up to a cap)
    - Latest judge verdict if any
    - Gate history if any
    - Path to the SKILL.md file in the ace plugin repo (relative path)
    - A short preamble explaining the improvement loop
→ returns {session_slug}
→ frontend navigates to /sessions/<slug>
```

**Why a system message, not a visible user turn:** the seed is scaffolding, not
conversation. It should render as a collapsed "context" block at the top of the
chat so the user's first real message can be "what do you think of this?" or
"the deploy step keeps failing on the Nova packaging — can you look at SKILL.md
and suggest a fix?"

**Session model changes.** A single migration on `apps/sessions/`:

- Add `opp_slug: CharField(max_length=64, blank=True, default="")`
- Add `opp_run_id: CharField(max_length=64, blank=True, default="")`
- Add `opp_step_skill: CharField(max_length=64, blank=True, default="")`
- Index on `(opp_slug, opp_run_id, opp_step_skill)` for the linked-chats query
- Keep `idd_ref` as-is — populated with the Drive file id of the opp's `idd.md`
- The legacy `opportunity_id` placeholder (`BigIntegerField`) from Phase 1 is
  left alone. It was designed for a Postgres-mirrored world that this spec
  moves away from; rather than dropping the column now, treat it as an unused
  no-op and remove it in a future cleanup migration.

**"Linked chats" list on the right pane** is
`Session.objects.filter(opp_slug=slug, opp_run_id=run, opp_step_skill=skill).order_by("-updated_at")[:10]`.

## 9. Non-goals (explicit exclusions)

- **No Postgres mirror of Drive state.** No `Opp`, `Run`, `Step`, `Artifact`,
  `JudgeResult`, `GateDecision` Django models. Drive is the store.
- **No live updates.** No WebSocket push, no SSE, no background sync. Each page
  load is a fresh read from Drive.
- **No trigger-a-run button.** Runs are initiated via the ACE plugin CLI.
  ace-web observes, it does not drive.
- **No in-app SKILL.md editor.** The chat harness is the editor — Claude in the
  chat reads the SKILL.md, proposes an edit, and pushes to GitHub.
- **No share tokens / public read-only links for v1.** Team shares Drive
  folders directly when they need to. Can be added later as a thin layer —
  reserved URL `/share-opp/<token>` not claimed.
- **No cross-opp trend dashboards** (judge-pass-rate histograms, time-to-live
  charts, etc.). The opp list + filters is the only aggregate surface.
- **No mobile responsive.** Desktop only, matching ace-web's existing decision.
- **No token-level artifact diffing** in the compare view. Side-by-side only.
- **No "start a new run from this IDD" button.** Triggered from the plugin CLI.

## 10. Coordination with the ACE plugin

This spec defines a Drive folder format that differs from what the ACE plugin
currently writes. Adopting it requires a companion change in the `ace` repo:

- Update each skill's SKILL.md / the orchestrator to write into
  `ACE/<opp-slug>/runs/<run-id>/steps/<ordinal>-<skill>/` instead of
  `ACE/<opp-slug>/<artifact-subfolder>/`
- Add `opp.yaml`, `run.yaml`, `step.yaml`, `events.jsonl` writers
- Ensure `skill_versions` is populated from git state at run time
- Deprecate `state.yaml` at the opp level in favor of `opp.yaml` + `run.yaml`

Until that change lands, ace-web's sync layer treats the flat layout as a
single implicit run with id `r1`. Both formats are supported from day one.

## 11. Testing strategy

- **Fixture-based tests** for the sync layer: commit a canonical example of
  each format (flat legacy + new structured) as a fixture under
  `tests/fixtures/drive/ACE/` and mock the `DriveClient` to read from the
  fixture tree. Every view and every extractor has fixture tests.
- **Extractor unit tests** — one test per per-skill extractor, pinned to a
  fixture artifact.
- **Auth flow integration test** — stand up a fake Google OAuth server and
  drive the `/auth/drive/start` + `/auth/drive/callback` cycle.
- **Chat seeding test** — POST `/discuss`, assert the resulting `Session` has
  the right pointer fields and the seed system message contains the expected
  structure.
- **Compare endpoint test** — fixture with two runs, assert the payload shape
  and delta computation.
- **End-to-end smoke** with a synthetic `CRISPR-Test-001` Drive fixture (can
  live in the same test fixtures directory; no live Drive call in CI).

## 12. Rollout

This is proposed as a self-contained plan, not forced into an existing phase
numbering (per the project's "plan boundaries are guidance" directive). It can
land in parallel with Phase 3 (multi-player collaboration) because it shares
nothing with the WebSocket / channels-redis work. It depends on:

- Phase 2's `Session` model and chat UI (already landed or landing) for the
  "Discuss in chat" integration
- ace-web's allauth + Connect OAuth identity flow being in place (in
  flight per the AWS pivot)
- A Google OAuth client registered with the correct dev + prod callback URIs

If those are ready, the implementation plan can start immediately.

## 13. Open risks

1. **Drive API latency across 19 step folders.** Worst-case an opp load could
   be 20–40 sequential file reads. The Google Drive API supports batch
   operations; the implementation must use them. If it still feels sluggish,
   the fallback is a thin Postgres snapshot table — which we can add without
   changing the format, because Drive stays the SoT. Explicitly deferred.
2. **ACE plugin format adoption takes time.** The flat-layout fallback lets
   ace-web ship before the plugin catches up, but users of the old format will
   see only one run per opp until the plugin migrates.
3. **Refresh token expiry** (Google revokes after 6 months of non-use, or on
   consent withdrawal). Handled by redirect-to-reconnect on refresh failure.
4. **Drive permission sprawl.** A user who loses Drive access to an opp folder
   mid-session gets a clean "you don't have access" error. No attempt to
   cache-through, no privilege escalation.
5. **`events.jsonl` growing unbounded** for long-running opps with recurring
   skills (`timeline-monitor`, `flw-data-review` weekly). Not a v1 problem;
   tail-read pattern handles it when it becomes one.

## 14. References

- Visual mockups (Workbench layout review):
  `.superpowers/brainstorm/53140-1775683599/content/workbench-dense.html`
- Google Drive OAuth + DriveClient pattern:
  `../connect-search/backend/app/core/{auth,drive}.py`,
  `../connect-search/backend/app/api/auth.py`
- ACE plugin design spec (current Drive folder conventions):
  `../ace/docs/superpowers/specs/2026-04-01-ace-design.md`
- ACE plugin playbook (the 19 skills and their current artifact shapes):
  `../ace/docs/generated/playbook.md`
- ace-web main design spec:
  `docs/specs/2026-04-08-ace-web-design.md`
- Scout-pattern AWS tenant deploy shape:
  `../scout-jjackson/.github/workflows/deploy-labs.yml`
- Relevant memory entries:
  - `project_drive_is_source_of_truth.md`
  - `project_ace_visualization_improvement_loop.md`
  - `feedback_visualization_no_live_updates.md`
  - `reference_connect_search_drive_oauth.md`
  - `project_aws_pivot.md`
