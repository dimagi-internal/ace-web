# Turmeric Smoke Walkthrough — Design

**Status:** Approved, pending implementation plan.
**Target:** prod (`labs.connect.dimagi.com/ace/`).
**Invocation:** human-driven via Claude Code; not a CI gate.

## 1. Goal

Produce a committed, repeatable, end-to-end smoke test for the ACE → Drive →
ace-web flow. Two entry paths (web wizard, CLI + upload) converge on the same
state — "Turmeric opp exists in Drive and is browseable in ace-web" — and are
verified by a single `canopy:walkthrough` scene set that exercises the Opp
Workbench, artifact previews, and seeded chat, then cleans up after itself.

This smoke test is how we catch regressions across the full stack:
ACE plugin orchestration, Drive service-account access, opps sync, Workbench
rendering, chat seeding, and the delete path. It runs against the live prod
deployment so it also exercises Drive, OAuth, and ingest credentials
end-to-end.

## 2. Non-goals

- Not a CI gate. `/ace:run` is LLM-driven, non-deterministic, and burns
  tokens on every run. The walkthrough is invoked manually before
  releases, after infra changes, or when investigating regressions.
- Not a replacement for the existing Playwright e2e suite under `e2e/`,
  which runs against a stubbed `FakeCLIBackend` and fake Redis and covers
  WebSocket, multiplayer, and upload mechanics deterministically.
- No undelete / restore UX. Drive's native trash (30-day recovery) is the
  only recovery path.
- No scene-level branching in the walkthrough YAML. Setup scripts handle
  path-specific work; the walkthrough is path-agnostic.

## 3. Architecture

### 3.1. Two setup scripts, one walkthrough

Both paths end with the same precondition: Turmeric opp lives in Drive
under `ACE_DRIVE_ROOT_FOLDER_ID`, with a timestamped slug
(`turmeric-smoketest-<YYYYMMDD-HHMM>`), and is listed in ace-web's
`/opps` for the current user. Once that state is reached, a single
`turmeric.yaml` walkthrough verifies rendering and tears down.

```
docs/walkthroughs/
├── turmeric.yaml              # single verify walkthrough
└── README.md                  # how to run each path

tools/walkthrough/
├── turmeric_pdd_finder.py     # locate latest Turmeric PDD in Drive
├── turmeric_web_setup.py      # Playwright: create opp via wizard
└── turmeric_cli_setup.sh      # /ace:run + ace-upload
```

Run flow:

- **Web path:** `python tools/walkthrough/turmeric_web_setup.py && /walkthrough turmeric`
- **CLI path:** `bash tools/walkthrough/turmeric_cli_setup.sh && /walkthrough turmeric`

The walkthrough finishes with a teardown scene that hits the new
`DELETE /api/opps/<slug>/` endpoint so the next run starts clean.

### 3.2. PDD Finder

`tools/walkthrough/turmeric_pdd_finder.py`:

1. Uses the existing `DriveClient` / `GoogleDriveClient` (same service
   account pattern as `apps/opps/`).
2. Lists subfolders under `ACE_DRIVE_ROOT_FOLDER_ID`.
3. Finds the one whose name contains `PDD` or `Program Design Doc`
   (case-insensitive). If multiple match, picks the most recently
   modified. Fails loudly if none.
4. Lists files in that subfolder whose name contains `turmeric`
   (case-insensitive). Picks the most recent by `modifiedTime`. Fails
   loudly if none.
5. Reads the body (Google Doc → export to markdown; plain file → read
   bytes as UTF-8).
6. Exposes `find_latest_turmeric_pdd() -> tuple[str, str]`
   (returns `(title, body)`).

Used by both setup scripts so the walkthrough evolves as the team
updates the canonical Turmeric PDD.

### 3.3. Web setup script

`tools/walkthrough/turmeric_web_setup.py`:

1. Calls `find_latest_turmeric_pdd()` for the idea text.
2. Launches Playwright with a persistent profile (`~/.ace/playwright-profile/`)
   so a pre-authenticated Dimagi OAuth session can be reused across runs.
   First run: human completes OAuth interactively; subsequent runs reuse
   cookies.
3. Navigates to `https://labs.connect.dimagi.com/ace/opps`.
4. Clicks "New Opp", fills the wizard with:
   - slug: `turmeric-smoketest-<YYYYMMDD-HHMM>`
   - name: `Turmeric Smoketest <timestamp>`
   - idea: body from PDD Finder
5. Submits, waits for the workbench URL to load.
6. Polls `GET /ace/api/opps/<slug>/` until it returns 200 (Drive sync
   complete).
7. Prints the slug to stdout for downstream consumption; writes
   `/tmp/turmeric-smoketest-slug.txt` for the walkthrough to read.
8. Exits 0 on success, non-zero with a diagnostic on any failure. The
   downstream `/walkthrough turmeric` invocation is gated on exit 0.

This script smoke-tests the full web-creation path: auth, wizard, API,
Drive write, workbench nav.

### 3.4. CLI setup script

`tools/walkthrough/turmeric_cli_setup.sh`:

1. Sources the PDD Finder via a small Python wrapper
   (`python -m tools.walkthrough.turmeric_pdd_finder --print-body`).
2. Computes `SLUG=turmeric-smoketest-$(date +%Y%m%d-%H%M)`.
3. Invokes `claude -p "/ace:run $SLUG --dry-run --mode auto"` with the
   PDD body piped in as context. (Exact piping mechanism — stdin or
   `--context-file` — needs verification against the current ACE plugin
   CLI contract; see Risks.)
4. Captures the Claude session's resulting `.jsonl` transcript path.
5. Runs `ace-upload <jsonl>` to push the transcript to
   `https://labs.connect.dimagi.com/ace/api/ingest/upload` via the
   personal token in `~/.ace/config.toml`.
6. Polls `GET /ace/api/opps/$SLUG/` until it returns 200.
7. Writes `SLUG` to `/tmp/turmeric-smoketest-slug.txt`.
8. Exits 0 on success.

This script smoke-tests the full CLI path: plugin orchestration, Drive
writes from the ACE run, JSONL transcript ingestion, and opp visibility.

### 3.5. Walkthrough YAML

`docs/walkthroughs/turmeric.yaml`:

- Reads the slug from `/tmp/turmeric-smoketest-slug.txt` in the first
  scene's `show` field via the standard walkthrough template-substitution
  pattern. (If `canopy:walkthrough` doesn't support file interpolation,
  the setup scripts instead `sed`-substitute the slug into a copy of the
  YAML before invoking. This falls out of implementation; the spec just
  requires the slug arrives at the walkthrough.)
- No `auth:` block in the YAML. Prod OAuth state is expected to live
  in the browse context's persistent storage from a prior interactive
  login. If the first scene lands on the OAuth login page, that's a
  clear signal the runner needs to re-auth; the README documents this.
- Nine scenes (see §4).

## 4. Walkthrough scenes

Entry precondition: `turmeric-smoketest-<slug>` exists in Drive, is
visible in `/opps`, has artifacts written by either setup path.

| # | Title                  | URL                               | Verify                                                      |
|---|------------------------|-----------------------------------|-------------------------------------------------------------|
| 1 | Opp list               | `/opps`                           | Turmeric row present with recent timestamp                  |
| 2 | Workbench loads        | `/opps/<slug>`                    | Three-pane renders: skills sidebar, artifact main, chat     |
| 3 | Phase 1 — idea         | sidebar `idea-to-pdd` selected    | Preview non-empty                                           |
| 4 | Phase 1 — PDD          | sidebar `pdd` selected            | Preview body contains text from the PDD Finder source       |
| 5 | Phase 2 — Learn app    | sidebar `pdd-to-learn-app`        | App summary preview non-empty                               |
| 6 | Phase 4 — OCS config   | sidebar `ocs-agent-setup`         | OCS agent config preview non-empty                          |
| 7 | Phase 6 — cycle grade  | sidebar `cycle-grade`             | Cycle-grade preview non-empty                               |
| 8 | Discuss in chat        | click "Discuss in chat" on step 4 | New chat tab opens; seed message contains skill name + slug |
| 9 | Teardown               | back to `/opps`, trash icon       | Confirm dialog → delete → row disappears                    |

Scoring uses the standard walkthrough rubric. Per-scene failures
(empty previews, missing rows) degrade individual scenes rather than
aborting the deck — a smoke test wants all the data points, not just
the first failure. Scene 9 is a functional check; its Demo Readiness
score is not rubric-graded in the usual sense.

The CLI path in `--dry-run` mode may legitimately not populate every
phase. Scenes 5–7 treat "preview empty" as a warning with a specific
message pointing at which phase didn't produce output, rather than a
hard fail. The expected-coverage matrix between `--dry-run` mode and
populated phases is documented in the walkthrough README and refined
as we observe real runs.

## 5. Delete-opp feature

New UI + API needed for teardown. Scoped minimally to the walkthrough's
needs but built as a proper app feature (not a test-only hatch).

### 5.1. Backend

- `DELETE /api/opps/<slug>/` in `apps/opps/views.py`.
- Handler:
  1. Look up the opp's Drive folder ID via `apps/opps/sync.py` helpers.
  2. Call `DriveClient.trash_folder(folder_id)` (new method — Drive
     trash, not permanent delete, so accidental deletes are recoverable
     for 30 days).
  3. Delete `Session` rows whose `seed_opp_slug == <slug>` (cascades to
     messages, drafts).
  4. Return `204 No Content` on success, `404` on missing opp, `500`
     with an envelope error on Drive failure.
- Auth: same session auth as the rest of `/api/opps/*`. No extra admin
  gate — any Dimagi user who can see the opp can delete it.
- Tests in `apps/opps/tests/test_delete.py`:
  - Opp exists → 204, folder trashed (mock), sessions gone.
  - Opp missing → 404.
  - Drive error → 500 with `{data: null, error: {...}}` envelope.

### 5.2. Frontend

- `deleteOpp(slug)` in `frontend/src/api/opps.ts`.
- `DeleteOppDialog.tsx`: shadcn `<Dialog>`, destructive button style,
  body text naming the slug and stating "this moves the Drive folder to
  trash and deletes all linked chat sessions."
- Trash icon entry points:
  - Opp list row — hover-reveal on the right.
  - Workbench header — overflow menu → "Delete opp."
- On success: toast ("Opp deleted"), refresh list, redirect from
  workbench to `/opps` if currently on a workbench page.

### 5.3. What delete does *not* do

- Does not delete FLW submissions in CommCare HQ.
- Does not revoke Connect opportunity config in production Connect.
  (Those are real-world artifacts; out of scope for a smoke-test
  teardown.)
- Does not touch `ace@dimagi-ai.com` mailbox drafts or sent mail.

For the walkthrough's target (smoke-test opps created from the
Turmeric PDD), no external Connect / CommCare state should exist in
the first place, since `--dry-run` suppresses all external calls and
the web-setup path goes through the wizard only.

## 6. Prod-run contract & safety

### 6.1. Credentials required on the runner's machine

- Dimagi Google login in a browser (for Drive, ace-web OAuth).
- `~/.ace/config.toml` with the `ace-upload` personal token. Token
  created from ace-web's Settings page, scoped to the logged-in user.
- Claude Code CLI authenticated (for the CLI path's `claude -p`
  invocation).
- Persistent Playwright profile at `~/.ace/playwright-profile/` with
  ace-web OAuth cookies. First run: human completes login manually;
  subsequent runs reuse.

### 6.2. Opp-slug hygiene

- Every run uses `turmeric-smoketest-<YYYYMMDD-HHMM>`. Minute-level
  precision means two runs in the same minute collide (acceptable —
  nobody is running this on a schedule).
- Both setup scripts check for leftover `turmeric-smoketest-*` opps
  at start. If found, print them and prompt. `--force-cleanup` flag
  skips the prompt and deletes leftovers before creating a new one.
- The walkthrough's teardown scene deletes its own opp on success.
  If the walkthrough aborts mid-deck, the leftover persists until
  the next run's `--force-cleanup` or manual cleanup via the UI.

### 6.3. Cost

- CLI path burns LLM tokens via `/ace:run` even in `--dry-run`. Rough
  estimate: a few dollars per run (refined after first successful
  runs). Documented in README.
- Web path is nearly free — just a Playwright session and a few API
  calls.

### 6.4. Blast radius on failure

- Worst case (setup-script aborts after Drive folder creation): a
  stranded `turmeric-smoketest-*` folder in Drive + an opp row visible
  to the logged-in user in `/opps`. Recoverable via the new delete UI
  or the next run's `--force-cleanup`.
- No production Connect or CommCare state is touched in either path
  (dry-run + wizard-only creation).
- Shared infra (RDS, ALB, ElastiCache): no changes. ace-web reads and
  writes to its existing database and Drive via the same code paths
  that serve normal users.

## 7. Risks & open questions

### R1. ACE CLI contract for seeding an opp from existing PDD text

The CLI setup script needs `/ace:run` to accept a PDD body as seed
instead of running `idea-to-pdd` from scratch. The current `/ace:run`
command takes only an `<opp-name>`. We need to confirm whether:

- **(a)** `/ace:run` can be invoked on a slug that already has `pdd.md`
  pre-written in Drive, and the orchestrator will skip Phase 1;
- **(b)** we should instead pre-populate Drive via a different ACE
  skill invocation (`/ace:step pdd-to-learn-app ...` starting from
  Phase 2); or
- **(c)** the CLI path should start from an idea and let
  `idea-to-pdd` regenerate the PDD, accepting that the CLI path tests
  a slightly different surface than the web path.

Resolution: check the ACE plugin orchestrator's behavior when
`pdd.md` already exists; update setup script accordingly. **Gate on
this before implementation.** If (c) is the answer, the web and CLI
paths remain valid but test slightly different things, which is
acceptable for a smoke test.

### R2. `canopy:walkthrough` YAML slug interpolation

The walkthrough needs to know the opp slug at scene-execution time.
Two fallback options ordered by preference:

1. If the skill supports env-var or file interpolation in `show`
   fields, use it.
2. Otherwise, setup scripts `sed`-substitute the slug into a copy of
   `turmeric.yaml` → `turmeric.rendered.yaml` before invoking
   `/walkthrough turmeric.rendered`. Works but leaves a generated
   file; `turmeric.rendered.yaml` is gitignored.

The implementation plan confirms which path the skill supports today
and picks one.

### R3. First-run OAuth for the Playwright persistent profile

Playwright's persistent profile needs a human to complete OAuth once.
The README documents this. `turmeric_web_setup.py` detects a stale /
missing session and prints clear instructions rather than failing
silently.

### R4. ace-upload config assumes per-machine setup

`~/.ace/config.toml` is manual per machine. That's OK for a
human-invoked smoke test. If we later want a service account to run
this, a separate design pass is needed.

## 8. Files & ownership

### New

- `docs/specs/2026-04-17-turmeric-smoke-walkthrough-design.md` (this
  file)
- `docs/walkthroughs/turmeric.yaml`
- `docs/walkthroughs/README.md`
- `tools/walkthrough/__init__.py`
- `tools/walkthrough/turmeric_pdd_finder.py`
- `tools/walkthrough/turmeric_web_setup.py`
- `tools/walkthrough/turmeric_cli_setup.sh`
- `apps/opps/tests/test_delete.py`
- `frontend/src/components/opps/DeleteOppDialog.tsx`

### Modified

- `apps/opps/views.py` — `DeleteOppView`
- `apps/opps/urls.py` — wire the route
- `apps/opps/sync.py` — `delete_opp_folder()` / `trash_folder()` helper
- `apps/opps/drive_client.py` — `trash_folder()` on ABC + Google impl
- `frontend/src/api/opps.ts` — `deleteOpp(slug)`
- `frontend/src/pages/OppListPage.tsx` — trash icon + dialog wiring
- `frontend/src/pages/OppWorkbenchPage.tsx` — header overflow menu +
  delete action

## 9. Implementation order (hand-off to writing-plans)

The `writing-plans` skill picks up here. A reasonable sequence is:

1. **Delete feature backend** — endpoint, `trash_folder()`, tests.
2. **Delete feature frontend** — dialog, trash icons, API client.
3. **PDD Finder module** — standalone, tested.
4. **Web setup script** — driven by PDD Finder, Playwright persistent
   profile, idempotency check.
5. **CLI setup script** — driven by PDD Finder, `ace-upload` wiring,
   resolves Risk R1.
6. **Walkthrough YAML** — scenes 1–9, slug interpolation per Risk R2.
7. **README** — covers first-run setup, cost, cleanup.
8. **First full run** — execute both paths against prod, capture the
   generated HTML decks, iterate on any low-scoring scenes.

Steps 1 + 2 (delete) are a prerequisite for step 6's teardown scene
and should land first as a standalone feature PR. The rest lands as a
second PR once delete is merged.
