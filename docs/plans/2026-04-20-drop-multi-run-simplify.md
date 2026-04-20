# Drop Multi-Run: Simplification Refactor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the dual Drive-layout problem between ace-web and the ACE plugin. Each opp is treated as a single run — no `runs/` subfolder, no `opp.yaml`/`run.yaml`/`step.yaml`. One flat Drive layout, owned by the ACE plugin. Make `/ace:run` scriptable end-to-end with optional ace-web transcript upload.

**Architecture:**
- **ACE plugin changes are purely additive.** Two new flags on `/ace:run` (`--idea FILE|-`, `--ace-web-url URL`) and one new skill (`ace:upload-transcript`). No existing behavior breaks; the flags default to current interactive behavior.
- **ace-web stops dictating Drive layout.** `opp_creator` writes only `idea.md`/`pdd.md` at the opp root; the invented `runs/run-001/state.yaml` is dropped. The still-existing structured-layout reader in `apps/opps/sync.py` becomes dead code for *new* opps but continues to read legacy opps created before this change — no migration needed. `OppWorkspace` gains a `tags` ArrayField for future grouping UI (no UI in this plan).
- **Lazy OppWorkspace materialization already works** (`opp_working_session` view creates rows on demand; opp list + workbench already fall back to flat layout). Nothing to add there — just verify it stays working once creation goes flat.

**Tech Stack:** Python 3.12, Django 5 + DRF, pytest, ACE plugin (markdown skills + TypeScript MCPs). Two repos: `/Users/jjackson/emdash-projects/worktrees/tumeric-12u` (ace-web, this repo) and `/Users/jjackson/emdash-projects/ace` (ACE plugin, vendored into ace-web at Docker build time via `ACE_REF` build arg).

**Sequencing constraint:** ACE plugin changes (Tasks 1–4) are additive and land first, in `../ace`. ace-web changes (Tasks 5–7) can land in parallel — they don't depend on the new ACE flags. Task 8 (Dockerfile bump) lands only after the ACE plugin changes are merged + tagged.

---

## Task 1: ACE plugin — `/ace:run --idea FILE|-` flag

**Files:**
- Modify: `/Users/jjackson/emdash-projects/ace/commands/run.md`
- Modify: `/Users/jjackson/emdash-projects/ace/agents/ace-orchestrator.md` (the "Starting a New Opportunity" section: step 2, `idea.md` capture)

Rationale: the orchestrator currently prompts via `AskUserQuestion` when `idea.md` is missing. Scripted runs need to pre-seed it from a file path or stdin so no interactive prompt fires.

- [ ] **Step 1: Update `commands/run.md` argument list**

In `/Users/jjackson/emdash-projects/ace/commands/run.md`, change the Arguments section to:

```markdown
## Arguments
- `<opp-name>` — name of the opportunity (used as the GDrive folder name)
- `--mode auto|review` — execution mode (default: review)
- `--idea FILE|-` — pre-seed `idea.md` from a file path, or `-` for stdin. When provided, skip the interactive `AskUserQuestion` prompt in "Starting a New Opportunity" step 2. Content is uploaded verbatim to `ACE/<opp-name>/idea.md` via `drive_create_file`.
- `--dry-run` — execute all skills but log effectful actions to `comms-log/dry-run-<step>.md` instead of performing them. Emails are not sent, apps are not published, tickets are not created. LLM-as-Judge and gates still apply. State tracks as `dry-run-success` or `dry-run-blocked`.
- `--sandbox` — route external API calls to staging endpoints. Connect calls go to staging Connect, CommCare calls go to the staging project space. Requires staging URLs configured in MCP server settings. Can be combined with `--dry-run`.
```

And add to the Process section, between steps 1 and 2:

```markdown
1a. If `--idea` was provided, read its body:
    - If the value is `-`, read stdin until EOF.
    - Otherwise treat the value as a file path; read its bytes as UTF-8.
    Pass the body through to the orchestrator alongside the opportunity name so the "Starting a New Opportunity" flow can skip its interactive prompt.
```

- [ ] **Step 2: Update `agents/ace-orchestrator.md` — Starting a New Opportunity step 2**

In `/Users/jjackson/emdash-projects/ace/agents/ace-orchestrator.md`, find the "Starting a New Opportunity" section (around line 325). Replace the bullet list under step 2 ("Ensure `idea.md` exists in the folder") with:

```markdown
2. **Ensure `idea.md` exists in the folder.** This is the single required human
   input — it's the raw idea or opportunity brief that `idea-to-pdd` iterates
   into a PDD. It is listed in `lib/artifact-manifest.ts` as
   `producedBy: 'external'`.

   - Use `drive_list_folder` on `ACE/<opp-name>/` to check for `idea.md`.
   - If `idea.md` is present, continue to step 3.
   - **If the operator passed `--idea FILE|-` to `/ace:run`**, the command
     has already loaded the body (from file or stdin). Write it verbatim
     to `ACE/<opp-name>/idea.md` with `drive_create_file` and continue.
     No `AskUserQuestion` prompt fires on this path — scripted runs are
     non-interactive by design.
   - Otherwise, **stop and ask the user for it** using `AskUserQuestion`.
     [...existing bullet list for Paste inline / Point at Drive doc / Abort...]
```

Keep the existing three `AskUserQuestion` options (paste inline, Drive doc, abort) intact — just guard the prompt path on "no `--idea` flag provided."

- [ ] **Step 3: Commit**

```bash
cd /Users/jjackson/emdash-projects/ace
git add commands/run.md agents/ace-orchestrator.md
git commit -m "feat(run): add --idea FILE|- flag for scripted idea.md seeding"
```

---

## Task 2: ACE plugin — `ace:upload-transcript` skill

**Files:**
- Create: `/Users/jjackson/emdash-projects/ace/skills/upload-transcript/SKILL.md`

Thin skill that POSTs a `.jsonl` transcript to `<ace-web-base-url>/api/ingest/upload` using the e2e-login auth flow (ACE_E2E_AUTH_TOKEN → session cookie). Pattern mirrors the three scripts we're about to delete in ace-web, consolidated into one place.

- [ ] **Step 1: Write the skill**

Create `/Users/jjackson/emdash-projects/ace/skills/upload-transcript/SKILL.md`:

```markdown
---
name: upload-transcript
description: Upload a Claude CLI stream-json transcript (.jsonl) to a deployed ace-web via /api/ingest/upload. Authenticates as ace@dimagi-ai.com via /auth/e2e-login/ using $ACE_E2E_AUTH_TOKEN (no personal bearer token required). Used by /ace:run --ace-web-url, or invoked directly for ad-hoc transcript uploads.
---

# upload-transcript

POSTs a `.jsonl` transcript file to `<base-url>/api/ingest/upload` so the
deployed ace-web can render it as a chat Session. Uses the e2e-login
shared-secret flow — no per-user personal tokens.

## Inputs

- `base_url` — deployed ace-web URL, e.g. `https://labs.connect.dimagi.com/ace`.
- `transcript_path` — filesystem path to a `.jsonl` file produced by
  `claude -p --output-format stream-json`.
- `ACE_E2E_AUTH_TOKEN` — env var; shared secret from the target instance's
  `deploy/aws/task-definition.json` or AWS Secrets Manager.

Optional: `email` (defaults to `ace@dimagi-ai.com`).

## Steps

1. **Verify preconditions.**
   - `transcript_path` exists and is non-empty.
   - `ACE_E2E_AUTH_TOKEN` is set in the environment.
   - `base_url` does not end in a trailing slash; strip if present.
   If any fail, stop and report which precondition failed.

2. **POST `/auth/e2e-login/`** with `{"email": <email>, "token": $ACE_E2E_AUTH_TOKEN}`
   using `curl -c <cookie-jar>` to persist the session cookie. Expect 200.
   On non-200, print the response body and fail. The cookie jar path can be
   a temp file (`mktemp`); clean up after.

3. **Warm `csrftoken_ace`** by GETting `<base-url>/` with the same cookie jar
   (`-b -c`). Django doesn't set the CSRF cookie until a view hit by
   `CsrfViewMiddleware` renders.

4. **POST `<base-url>/api/ingest/upload`** with:
   - `-b <cookie-jar>` for the `sessionid_ace` session cookie
   - `-H "X-CSRFToken: <csrf-value-from-jar>"`
   - `-H "Referer: <base-url>/"`
   - `-F "file=@<transcript_path>;type=application/x-ndjson"`
   Expect 201. On non-201, print the response body and fail.

5. **Return** the `data.session_slug` from the 201 response envelope as the
   skill's output. Callers (e.g. `/ace:run --ace-web-url`) can log the
   resulting URL: `<base-url>/chat/<session_slug>`.

## Shell reference

```bash
COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

# 1. login
curl -sS -c "$COOKIE_JAR" -o /dev/null -w '%{http_code}' \
  -X POST "$BASE_URL/auth/e2e-login/" \
  -H "Content-Type: application/json" \
  --data-raw "{\"email\":\"ace@dimagi-ai.com\",\"token\":\"$ACE_E2E_AUTH_TOKEN\"}"

# 2. warm csrf
curl -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o /dev/null "$BASE_URL/"
CSRF=$(awk '$6 == "csrftoken_ace" { print $7 }' "$COOKIE_JAR" | tail -n 1)

# 3. upload
curl -sS -b "$COOKIE_JAR" -w '%{http_code}' \
  -X POST "$BASE_URL/api/ingest/upload" \
  -H "X-CSRFToken: $CSRF" \
  -H "Referer: $BASE_URL/" \
  -F "file=@$TRANSCRIPT_PATH;type=application/x-ndjson"
```

## Failure modes

| HTTP | Cause | Remedy |
|------|-------|--------|
| 401  | `sessionid_ace` missing/expired | Re-run e2e-login; check token value. |
| 403  | e2e-login route disabled (instance has `ACE_E2E_AUTH_TOKEN` empty) | Set the env var on the target deployment. |
| 409  | Transcript already uploaded (duplicate `cli_session_id`) | Expected on re-runs; treat as success for idempotency. |
| 400 "file is required" | Multipart malformed | Check that the `-F "file=@..."` form field is present. |

## Reference

- `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/docs/architecture/cli-credentials.md` (for the broader auth model context — this skill uses the *e2e* flow, not the per-user CLI credential flow).
- `apps/ingest/views.py` in ace-web defines the upload endpoint (`IsAuthenticated`, `MultiPartParser`).
```

- [ ] **Step 2: Commit**

```bash
cd /Users/jjackson/emdash-projects/ace
git add skills/upload-transcript/SKILL.md
git commit -m "feat(skills): add upload-transcript skill for ace-web transcript ingest"
```

---

## Task 3: ACE plugin — `/ace:run --ace-web-url URL` flag

**Files:**
- Modify: `/Users/jjackson/emdash-projects/ace/commands/run.md`
- Modify: `/Users/jjackson/emdash-projects/ace/agents/ace-orchestrator.md` (add a post-run upload hook)

- [ ] **Step 1: Extend `commands/run.md` argument list**

Append to the Arguments section:

```markdown
- `--ace-web-url URL` — optional. After the orchestrator completes (success or failure), invoke the `upload-transcript` skill to POST the current session's stream-json transcript to `<URL>/api/ingest/upload`. Requires `ACE_E2E_AUTH_TOKEN` in the environment. No-op if absent. On upload success, logs the resulting chat URL (`<URL>/chat/<session_slug>`) to the operator.
```

And in the Process section, add step 3:

```markdown
3. After the orchestrator returns, if `--ace-web-url` was provided:
   - Resolve the path of the current stream-json transcript (the `.jsonl`
     file the operator is recording, typically via
     `claude -p --output-format stream-json > <file>`). If the transcript
     path is not available in the run context, log a warning and skip
     the upload — do not fail the overall run.
   - Dispatch the `upload-transcript` skill with `base_url=<URL>` and
     `transcript_path=<resolved-path>`.
   - Log the returned `session_slug` and the viewable URL
     (`<URL>/chat/<session_slug>`) to the operator's console.
```

- [ ] **Step 2: Update `agents/ace-orchestrator.md` — post-run hook**

Add a new section after "Between Phases" (around line 185):

```markdown
## Post-Run: ace-web Transcript Upload (optional)

When `/ace:run` is invoked with `--ace-web-url URL`, after all phases
complete (or on fatal error) the orchestrator dispatches the
`upload-transcript` skill with the current transcript path and the
provided base URL. This is a best-effort hook — an upload failure is
logged but does not alter the run's success/failure status.

Requirements:
- `ACE_E2E_AUTH_TOKEN` must be set in the environment. If absent, log a
  warning and skip the upload.
- The transcript path is whatever the operator is writing stream-json to
  (typically `$JSONL_PATH` in a scripted run). If not resolvable, skip.

This is the only ace-web dependency in the ACE plugin. Without `--ace-web-url`
the plugin is entirely standalone.
```

- [ ] **Step 3: Commit**

```bash
cd /Users/jjackson/emdash-projects/ace
git add commands/run.md agents/ace-orchestrator.md
git commit -m "feat(run): add --ace-web-url flag for optional transcript upload"
```

---

## Task 4: ACE plugin — VERSION bump, CHANGELOG, merge

**Files:**
- Modify: `/Users/jjackson/emdash-projects/ace/VERSION`
- Modify: `/Users/jjackson/emdash-projects/ace/CHANGELOG.md`

- [ ] **Step 1: Bump VERSION to 0.5.0**

Current is `0.4.5`. New features → minor bump.

```bash
cd /Users/jjackson/emdash-projects/ace
echo "0.5.0" > VERSION
```

- [ ] **Step 2: Prepend a 0.5.0 entry to CHANGELOG.md**

Insert after the `# Changelog` header and before `## 0.4.5 — 2026-04-19`:

```markdown
## 0.5.0 — 2026-04-20

Feature: scripted end-to-end runs with optional ace-web transcript upload.

### Added

- **`/ace:run --idea FILE|-`** — pre-seed `idea.md` from a file path or
  stdin, skipping the interactive `AskUserQuestion` prompt in the
  "Starting a New Opportunity" flow. Enables fully non-interactive
  lifecycle runs (smoke tests, CI-style invocations, scripted demos).
- **`/ace:run --ace-web-url URL`** — after the orchestrator returns,
  upload the run's stream-json transcript to `<URL>/api/ingest/upload`
  so the deployed ace-web can render it as a chat Session. Requires
  `ACE_E2E_AUTH_TOKEN` in the environment. No-op if the flag is absent;
  the plugin remains standalone.
- **`skills/upload-transcript/`** — new skill encapsulating the
  e2e-login + `/api/ingest/upload` flow. Invoked by `--ace-web-url`;
  can also be called directly for ad-hoc transcript uploads.
```

- [ ] **Step 3: Commit, PR, tag**

```bash
cd /Users/jjackson/emdash-projects/ace
git add VERSION CHANGELOG.md
git commit -m "release: 0.5.0 — scripted /ace:run + optional transcript upload"
git push origin HEAD
# Open PR, merge, then:
git checkout main && git pull
git tag v0.5.0 && git push origin v0.5.0
```

---

## Task 5: ace-web — `opp_creator` stops writing `runs/`

**Files:**
- Modify: `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/apps/opps/opp_creator.py:64-82`
- Modify: `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/apps/opps/tests/test_create_opp.py`

Stop writing `runs/run-001/state.yaml`. Opp folder becomes `ACE/<slug>/` with `idea.md` (and optional `pdd.md`) at the root — matching exactly what `/ace:run` will create/read.

- [ ] **Step 1: Write the failing test**

Open `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/apps/opps/tests/test_create_opp.py` and add a test that asserts `create_opp` does NOT create a `runs/` subfolder or `state.yaml`:

```python
def test_create_opp_writes_flat_layout_no_runs_subfolder(user, fake_drive, settings):
    """New opps are flat: idea.md (+ optional pdd.md) at the opp root, no runs/ subfolder.
    See docs/plans/2026-04-20-drop-multi-run-simplify.md."""
    result = create_opp(
        drive=fake_drive,
        ace_root_folder_id="ACE",
        owner=user,
        slug="flat-test",
        display_name="Flat Test",
        idea="the idea body",
        mode="review",
    )
    opp_children = {f.name for f in fake_drive.list_files(result.workspace.slug)}
    assert "idea.md" in opp_children
    assert "runs" not in opp_children, "opp_creator must not create a runs/ subfolder"
    assert "state.yaml" not in opp_children, "opp_creator must not write state.yaml — /ace:run owns state"
```

- [ ] **Step 2: Run the test — expect it to fail**

```bash
cd /Users/jjackson/emdash-projects/worktrees/tumeric-12u
pytest apps/opps/tests/test_create_opp.py::test_create_opp_writes_flat_layout_no_runs_subfolder -v
```

Expected: FAIL — current code creates both `runs/` subfolder and `runs/run-001/state.yaml`.

- [ ] **Step 3: Edit `opp_creator.py` to drop the runs-folder writes**

Replace lines 64–82 of `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/apps/opps/opp_creator.py`:

```python
    # Drive writes (outside the Postgres transaction). Flat layout:
    # ACE/<slug>/{idea.md, pdd.md?}. The ACE plugin (/ace:run) owns state.yaml
    # and writes it directly at the opp root when the lifecycle starts.
    opp_folder_id = drive.create_folder(ace_root_folder_id, slug)
    drive.upload_file(opp_folder_id, "idea.md", idea, "text/markdown")
    if pdd:
        drive.upload_file(opp_folder_id, "pdd.md", pdd, "text/markdown")
```

(Removes the `runs_folder_id`, `run1_folder_id`, `state_lines`, `state_yaml`, and the `runs/run-001/state.yaml` upload. `display_name` persistence is handled by the `OppWorkspace` DB row.)

- [ ] **Step 4: Run the test — expect it to pass**

```bash
pytest apps/opps/tests/test_create_opp.py::test_create_opp_writes_flat_layout_no_runs_subfolder -v
```

Expected: PASS.

- [ ] **Step 5: Run the full opps test suite — catch any other assumptions**

```bash
pytest apps/opps/tests/ -v
```

Expected: all pass. If any fail because a test was relying on `runs/run-001/state.yaml` being written at create time, fix the test to match the new flat layout (tests that verify Drive state should check the opp root directly, not a `runs/run-001/` subfolder).

- [ ] **Step 6: Commit**

```bash
git add apps/opps/opp_creator.py apps/opps/tests/test_create_opp.py
git commit -m "refactor(opps): opp_creator writes flat Drive layout (drop runs/run-001/)"
```

---

## Task 6: ace-web — add `tags` field to `OppWorkspace`

**Files:**
- Modify: `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/apps/opps/models.py`
- Create: `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/apps/opps/migrations/000X_add_workspace_tags.py` (auto-generated — exact number depends on current migration count)

Adds a free-form string ArrayField for grouping related opps. No UI in this plan — just persist. Later work: tag filter + side-by-side comparison view.

- [ ] **Step 1: Write the failing test**

Append to `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/apps/opps/tests/test_models.py` (or create if missing):

```python
def test_opp_workspace_tags_default_empty_and_settable(user):
    from apps.opps.models import OppWorkspace
    ws = OppWorkspace.objects.create(
        slug="tagged-opp", display_name="Tagged Opp", created_by=user,
    )
    assert ws.tags == []
    ws.tags = ["turmeric", "smoke-test"]
    ws.save()
    ws.refresh_from_db()
    assert ws.tags == ["turmeric", "smoke-test"]
```

- [ ] **Step 2: Run — expect AttributeError / FieldDoesNotExist**

```bash
pytest apps/opps/tests/test_models.py::test_opp_workspace_tags_default_empty_and_settable -v
```

- [ ] **Step 3: Add the field**

In `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/apps/opps/models.py`, add:

```python
from django.contrib.postgres.fields import ArrayField
```

and inside the `OppWorkspace` class, before `created_at`:

```python
    tags = ArrayField(
        models.CharField(max_length=64),
        default=list,
        blank=True,
        help_text=(
            "Free-form tags for grouping related opps (e.g. iterations of the "
            "same idea). Future UI will expose tag filters and side-by-side "
            "comparison. See docs/plans/2026-04-20-drop-multi-run-simplify.md."
        ),
    )
```

- [ ] **Step 4: Generate the migration**

```bash
cd /Users/jjackson/emdash-projects/worktrees/tumeric-12u
docker compose run --rm web python manage.py makemigrations opps
```

Expect a new file under `apps/opps/migrations/` adding the `tags` field with `default=list`.

- [ ] **Step 5: Run the test — expect pass**

```bash
pytest apps/opps/tests/test_models.py::test_opp_workspace_tags_default_empty_and_settable -v
```

Expected: PASS (pytest applies migrations against the in-memory SQLite test DB automatically — `JSONField`-like semantics on SQLite still honor `default=list` via Django's `ArrayField` sqlite compat layer; if the test runner complains about postgres-only field, use `from django.db import models` + `models.JSONField(default=list)` instead since we don't index on tags).

Note: if the SQLite test DB balks at `ArrayField`, swap to `models.JSONField(default=list)` — the storage difference is immaterial since we're not indexing on tags, and the API surface is identical.

- [ ] **Step 6: Commit**

```bash
git add apps/opps/models.py apps/opps/migrations/ apps/opps/tests/test_models.py
git commit -m "feat(opps): add tags field to OppWorkspace for future grouping UI"
```

---

## Task 7: ace-web — delete the three turmeric auth scripts + update docs

**Files:**
- Delete: `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/tools/walkthrough/turmeric_cli_setup.sh`
- Delete: `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/tools/walkthrough/turmeric_auth_login.sh`
- Delete: `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/tools/walkthrough/turmeric_auth_check.sh`
- Modify: `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/docs/walkthroughs/README.md`
- Modify: `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/docs/walkthroughs/turmeric-end-to-end.yaml` (preamble comment block)
- Modify: `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/docs/walkthroughs/turmeric-step1-web.yaml` (if its `auth.check`/`auth.login` hooks still reference the deleted scripts — update to the new recipe or remove)

Keep: `turmeric_pdd_finder.py` (reusable Drive-lookup utility) and `turmeric_data_check.sh` (walkthrough precondition verifier that inspects opp state — unrelated to auth plumbing).

- [ ] **Step 1: Verify what references the doomed scripts**

```bash
cd /Users/jjackson/emdash-projects/worktrees/tumeric-12u
grep -rn "turmeric_auth_login\|turmeric_auth_check\|turmeric_cli_setup" --include="*.sh" --include="*.yaml" --include="*.md" --include="*.py"
```

Expected hits: `docs/walkthroughs/README.md`, `docs/walkthroughs/turmeric-step1-web.yaml`, `docs/walkthroughs/turmeric-end-to-end.yaml` preamble, and the scripts themselves. Any hits in the `tests/` tree should be updated too.

- [ ] **Step 2: Delete the three scripts**

```bash
git rm tools/walkthrough/turmeric_cli_setup.sh \
       tools/walkthrough/turmeric_auth_login.sh \
       tools/walkthrough/turmeric_auth_check.sh
```

- [ ] **Step 3: Rewrite the CLI-path section in `docs/walkthroughs/README.md`**

Replace the "CLI path" section (lines 85–107) with:

```markdown
## CLI path

```bash
# 1. Fetch the Turmeric PDD to a local file
python tools/walkthrough/turmeric_pdd_finder.py > /tmp/turmeric-smoketest/pdd.txt

# 2. Run the full lifecycle. /ace:run creates the Drive folder + idea.md,
#    dispatches the orchestrator, and (via --ace-web-url) uploads the
#    stream-json transcript to ace-web when the run completes.
SLUG="turmeric-smoketest-$(date +%Y%m%d-%H%M)"
export ACE_E2E_AUTH_TOKEN="<value from deploy/aws/task-definition.json>"

claude -p "/ace:run $SLUG --mode auto --idea /tmp/turmeric-smoketest/pdd.txt --ace-web-url https://labs.connect.dimagi.com/ace" \
  --output-format stream-json --verbose \
  > /tmp/turmeric-smoketest/transcript-$SLUG.jsonl

# 3. Verify the opp is populated (≥6 skills complete) before running the walkthrough:
echo "$SLUG" > /tmp/turmeric-smoketest/slug.txt
bash tools/walkthrough/turmeric_data_check.sh

# 4. In Claude Code:
/walkthrough turmeric-end-to-end
```

`/ace:run` handles all the work the old `turmeric_cli_setup.sh` did:
- Creates `ACE/<slug>/` on Drive and seeds `idea.md` from `--idea` (flat layout; the ACE plugin owns state).
- Orchestrates phases 1→4 via the `ace-orchestrator` agent (stop before Phase 5 by interrupting or using `--dry-run` if you just want a cheap smoke).
- On completion, `--ace-web-url` dispatches the `upload-transcript` skill to POST the `.jsonl` transcript to `/api/ingest/upload`. ace-web's `/opps` list picks up the new Drive folder automatically; `OppWorkspace` materializes lazily on first view.

**Cost note:** a full real run (no `--dry-run`) burns significant LLM tokens
(Nova calls for Learn/Deliver apps, app-test evaluation loop, OCS agent
clone + RAG build). Budget accordingly.
```

- [ ] **Step 4: Update the walkthrough YAML preambles**

In `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/docs/walkthroughs/turmeric-end-to-end.yaml`, rewrite the setup comment block (lines 5–29) with the new recipe from Step 3. Replace references to `turmeric_cli_setup.sh` and the `--dry-run` wrapper.

In `/Users/jjackson/emdash-projects/worktrees/tumeric-12u/docs/walkthroughs/turmeric-step1-web.yaml`, update any `auth.check`/`auth.login` hooks that call the deleted scripts. Options:
- Inline the e2e-login curl flow into the yaml's `auth.login.command` (short — three curl calls from Task 2's "Shell reference").
- Or — simpler — drop the `auth.*` hooks entirely if the walkthrough is expected to run in a Claude Code session that has already authenticated via the browser. Pick based on how `canopy:walkthrough` currently invokes the yaml; don't overbuild.

- [ ] **Step 5: Run the test suite — catch any test references to deleted paths**

```bash
pytest -v -k "turmeric or walkthrough"
```

Expected: pass, or fix obvious broken imports. There shouldn't be Python tests against the deleted shell scripts.

- [ ] **Step 6: Commit**

```bash
git add -A tools/walkthrough/ docs/walkthroughs/
git commit -m "refactor(walkthroughs): delete auth scripts, use /ace:run --idea --ace-web-url"
```

---

## Task 8: ace-web — bump vendored ACE plugin version

**Files:**
- The ACE plugin is vendored at build time via `ARG ACE_REF=main` in `Dockerfile`. The layer cache busts when the remote `main` SHA moves (see `build-backend.yml`'s `ACE_REF` computation). So **no file edit is required** — just trigger a rebuild after Task 4's PR lands.

**Prerequisite:** Task 4 must be merged to `jjackson/ace` `main` and tagged `v0.5.0`.

- [ ] **Step 1: Verify the vendored ACE plugin picked up 0.5.0**

Push whatever ace-web commit you have (from Tasks 5–7) to trigger `build-backend.yml`. Once the build completes:

```bash
gh run list --workflow=build-backend.yml --limit=1
```

- [ ] **Step 2: Deploy to labs**

```bash
gh workflow run deploy-labs.yml --ref main -f run_migrations=true
gh run watch
```

`run_migrations=true` applies the new `OppWorkspace.tags` migration.

- [ ] **Step 3: Verify System tab shows ACE 0.5.0**

Open `https://labs.connect.dimagi.com/ace/system` in a browser and confirm the vendored ACE plugin version is `0.5.0`. The System tab reads `VERSION` from `/app/vendor/ace/` inside the container.

- [ ] **Step 4: Smoke test the end-to-end recipe**

Run the CLI-path recipe from the updated `docs/walkthroughs/README.md` against labs:

```bash
export ACE_E2E_AUTH_TOKEN="..."
SLUG="turmeric-smoketest-$(date +%Y%m%d-%H%M)"
python tools/walkthrough/turmeric_pdd_finder.py > /tmp/turmeric-smoketest/pdd.txt
mkdir -p /tmp/turmeric-smoketest
claude -p "/ace:run $SLUG --mode auto --dry-run --idea /tmp/turmeric-smoketest/pdd.txt --ace-web-url https://labs.connect.dimagi.com/ace" \
  --output-format stream-json --verbose \
  > /tmp/turmeric-smoketest/transcript.jsonl
```

Use `--dry-run` for this first verification — a full real run is expensive; we only need to confirm the new flags + upload hook fire correctly. Check:
- `/ace:run` did not prompt interactively (the `--idea` flag suppressed the `AskUserQuestion`).
- The transcript uploaded: visit `https://labs.connect.dimagi.com/ace/opps` and find the new `turmeric-smoketest-<stamp>` card. Click through to its workbench. The Drive folder should be flat (no `runs/` subfolder).
- The ingested chat Session is viewable at `https://labs.connect.dimagi.com/ace/chat/<session-slug>` (slug printed by the `upload-transcript` skill).

---

## Notes on deferred work

Out of scope for this plan — flagged here for future scoping:

1. **Structured-layout reader cleanup.** `apps/opps/sync.py` still contains the structured-layout reader (`load_opp` main path + parsers for `opp.yaml`, `run.yaml`, `step.yaml`), plus `fork_run` in `apps/opps/fork.py` and the `/api/opps/<slug>/compare` endpoint. These become unused for *new* opps after Task 5 but continue to read any legacy opps on Drive with `runs/run-001/state.yaml`. A future cleanup can delete all of that (and the `opp_run_id` / `opp_step_skill` fields on `Session`) once the last structured-layout opp has been trashed from Drive. ~500 LOC deletion; zero behavioral change for new opps.
2. **Tag UI.** This plan adds the `tags` field; the filter UI and opp-comparison view come later. Rough sketch: `OppList` gets a tag filter pill; a `CompareOpps` view accepts `?tags=turmeric` and renders judge-score + step-status side-by-side across matching opps.
3. **`ace-upload` CLI rationalization.** `apps/ingest/cli.py` defines a standalone `ace-upload` tool that uses personal bearer tokens. The new `ace:upload-transcript` skill uses the e2e-login shared-secret. Both continue to work — they target the same endpoint with different auth. If we want to consolidate later, the skill could shell out to `ace-upload` with the shared secret swapped in, or `ace-upload` could learn the e2e-login flow. Neither is urgent.
