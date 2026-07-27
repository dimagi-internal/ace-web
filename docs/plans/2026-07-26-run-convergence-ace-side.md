# Run-execution convergence — ace-web side Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ace-web stops being a second execution engine. Its programmatic ACE runs enqueue a canopy `Turn` against a canopy `Session` instead of spawning `claude -p` in-process; cost and structure derive from canopy's retained per-turn transcript; and a run that no runner can take says so in plain words instead of rendering as "queued".

**Spec:** canopy-web `docs/superpowers/specs/2026-07-26-run-execution-convergence-design.md`. **Items 4, 5 and 6 of "Shape of the work" are this plan's scope.** Items 1–3 are canopy-side (`docs/superpowers/plans/2026-07-26-run-convergence-canopy-side.md`) — PR 1 (retained transcript) has shipped; PRs 2 and 3 have not (see "Hard dependency" below).

**Architecture:** Every programmatic run in ace-web funnels through one shape today — build a completed `role="user"` `Message` plus a pending `role="assistant"` `Message`, then call `apps.sessions.turn_driver.start_turn_subprocess(assistant_message_id)`. There are **exactly three** production call sites of that function. This plan replaces that one function with `apps.canopy.run_dispatch.dispatch_turn(assistant_message_id)`, which creates/reuses **one canopy `Session` per ace-web `Session`** (which is already 1:1 with an opp-run) and enqueues a **session-targeted** Turn via `POST {canopy}/api/canopy-sessions/{id}/send`. ace-web's own `Session`/`Message`/`SessionParticipant`/`IngestUpload` rows stay exactly where they are and keep exactly the jobs they have — they become the local ledger and index of a run whose *execution* happens elsewhere.

**Tech Stack:** Django 5 + django-ninja 1.x + Pydantic v2 + django-environ; `urllib.request` for outbound canopy calls (the existing `apps/canopy/client.py` convention — no new HTTP dependency); React 19 + Vite + Tailwind 4 + `canopy-ui`; pytest (settings `config.settings.test`), vitest.

---

## Critical context: what stays, what changes, what goes

A previous plan proposed deleting `apps/sessions`' models as "legacy chat". **That would have destroyed production infrastructure.** The models' own docstring says so (`apps/sessions/models.py:1-16`):

> Session + Message are NOT chat-only: they're the record of every assistant turn ACE drives, whether from a human typing (retired — see canopy-web) or a programmatic run (`apps.opps.api::seeded_run`, the `drive_turn` mgmt command, Slack-triggered runs).

ace-web's `Session` is a **homonym** of canopy's `Session`, not a duplicate of it. canopy's `Session` is a chat conversation. ace-web's `Session` is an **opp-run record**: it carries `opp_slug`/`opp_run_id`/`opp_step_skill` (indexed as `idx_session_opp_step`), owns the `cost_breakdown` the analyzer reads, owns the `driver_heartbeat_at` liveness beacon the post-deploy self-heal reads, and is the parent of the `IngestUpload` row that powers `/structure`. Deleting it deletes the run history.

The verdict, resource by resource:

| Resource | Verdict | Why |
|---|---|---|
| `apps/sessions.Session` | **STAYS.** Gains `canopy_session_id`. | The opp-run record. 1:1 with a canopy Session after this plan. |
| `apps/sessions.Message` | **STAYS.** Gains `canopy_turn_id`. | The per-turn ledger; `status` drives `interrupted()` / `resumable_after_deploy()`. |
| `apps/sessions.SessionParticipant` | **STAYS, untouched.** | Written by `Session.create_with_owner`; read by `GET /{slug}/participants` and the admin. Not load-bearing for execution, but removing it is out of scope and unrelated. |
| `apps/sessions.IngestUpload` | **STAYS.** Gains `source` + `canopy_turn_ids`. Demoted from source-of-record to **cache** for canopy-executed sessions. | Still the sole source for *uploaded* transcripts (`POST /api/ingest/upload`) and for every pre-migration row. |
| `apps/sessions/turn_driver.py` | **RETIRED — but only at Task 12, and only once its preconditions hold.** | See Task 12. It cannot be retired inside this plan's scope; the preconditions are not satisfiable without a cloud runner. |
| `apps/sessions/management/commands/drive_turn.py` | **RETIRED with `turn_driver`, at Task 12.** | It is not an independent caller: it is the *subprocess entrypoint* `start_turn_subprocess` spawns (`turn_driver.py:465-474`). Migrating it separately is meaningless — it dies with the driver. |
| `apps/common/cli_backend.py` (`CLIBackend`) | **OUT OF SCOPE, stays.** | Still used by `apps/sessions/auto_title.py` and the backend selector. Retiring it is a follow-on to Task 12, not part of it. |
| `apps/slack/run_starter.py` | **NOT MIGRATED.** Made honest instead. | It never executed anything. See "The Slack path" below. |

---

## The Slack path: resolved

The spec flagged this unresolved. It is now resolved, with evidence.

**`/ace run <existing-slug>` is LATENT.** `apps/slack/run_starter.py:126-144` creates a `Session` and a single `role="user"`, `status="complete"` `Message`, then `return slug, run_id`. It creates **no assistant placeholder** and imports **nothing** from `apps.sessions.turn_driver`. There are no Django signals in this repo (`grep -rn "post_save|pre_save|@receiver"` → zero hits), no Celery (zero hits), no custom `Message.save()`, and the WebSocket consumer that used to spawn turns was deleted in `3a996df`. The post-deploy sweep cannot rescue it either: `Session.resumable_after_deploy()` and `Session.interrupted()` (`apps/sessions/models.py:170-230`) both require `messages__role="assistant"` — a row this path never writes. The `content={"type":"text","source":"slack-trigger"}` marker it writes has exactly one occurrence in the repo: the line that writes it.

**`/ace new` and `/ace run <pdd-link>` are BROKEN.** `run_starter.py:93` does `GoogleDriveClient(settings.ACE_DRIVE_SA_KEY_JSON)` — passing a raw JSON **string** where `googleapiclient.discovery.build` wants a credentials **object**. It is the only hand-constructed `GoogleDriveClient` in the repo; every other caller uses `apps/opps/drive_client.py:472 get_drive_client()`. The resulting `AttributeError: 'str' object has no attribute 'authorize'` is swallowed by the bare `except Exception` at `verbs_run.py:73-78` / `verbs_new.py:109-112`, which reply "Internal error starting run." Nothing is created.

**It was never wired.** `git log --follow -- apps/slack/run_starter.py` has two commits; the birth commit `6c9cb57` already ends at `return slug, run_id`, and `932d54a` is a lint pass. The claim came from a design doc (`docs/superpowers/specs/2026-05-15-slack-integration-design.md:94-96`: "→ existing turn_driver spawns claude -p") that was transcribed into the module docstring at `run_starter.py:14` and shipped. Every test mocks `start_run_from_slack` out of existence, so CI has been green since May.

**Consequence for this plan:** there is no Slack caller to migrate. Task 11 makes the surface honest (fix the false docstring, the false `CLAUDE.md:275` claim, and the crashing Drive-client call) and wires it through the *new* seam so it works for the first time — which is a fix, not a migration, and is why it lands last and separately.

---

## Hard dependency: this plan ships DARK

**There is no cloud runner online, and standing one up is out of scope** (spec, "Out of scope"). canopy-side PR 2 — the one that makes the cloud runner session-capable — has not shipped. `claim_next_turn` gates session-targeted turns on `runner.session_capable()` (`capabilities.sessions == true`), and no runner declares it.

Therefore: **every turn this plan enqueues will sit `QUEUED` forever.** That is not a defect to design around — it is the day-one behaviour, and it is precisely why Item 6 (Tasks 5–7) is a first-class run state and not an error banner. It also means:

- `CANOPY_RUN_EXECUTION` defaults to **`False`**. Flipping it on with no runner takes ACE runs from "works locally" to "nothing runs". The flag is the whole safety story.
- Task 12 (retire `turn_driver`) **cannot execute in this plan**. Its preconditions are written out; they are not satisfiable today.
- Tasks 1–11 are still worth shipping now: they are inert behind the flag, they are individually testable against a mocked canopy, and they are the thing that becomes correct the moment a runner exists.

## Global Constraints

- Backend tests: `uv run pytest tests/<file> -v` for a single file; `uv run pytest` (full suite) once before each commit. Settings module is `config.settings.test`; `addopts = "-m 'not contract'"` so contract tests are opt-in via `-m contract`.
- Frontend: `cd frontend && npm run test` (vitest) and `npm run build` (type check).
- **Regenerate OpenAPI types whenever an `apps/**/schemas.py` or `apps/**/api.py` changes**, and commit `frontend/src/api/generated.ts` with the same commit.
- New Ninja routers/routes follow the repo pattern: `Router(auth=session_auth, tags=[…])` in `apps/<app>/api.py`, registered in `apps/api/api.py` via `api.add_router(...)` with deferred imports at the bottom (`# noqa: E402`).
- Settings via `django-environ` in `config/settings/base.py` (`env("NAME", default=…)`); secrets never get real defaults.
- Outbound canopy calls use `urllib.request` in `apps/canopy/client.py`, matching the existing two calls. **Do not add `httpx` here** — see Task 7 for why the wire format makes the choice of client load-bearing.
- New `IngestUpload`/`Session`/`Message` schema changes go in **`apps/sessions/migrations/`** (app label `ace_sessions`; next number is `0010`). `apps/ingest` has **no models and no migrations** — it is a pure logic + API app.
- Commit messages end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- PR bodies end with: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`
- One branch per PR, off `origin/main`. Open PRs with auto-merge armed: `gh pr merge <n> --auto --squash`.

## File Structure

| File | Responsibility | PR |
|---|---|---|
| `config/settings/base.py` | `CANOPY_RUN_EXECUTION`, `CANOPY_RUN_ACTOR_FALLBACK_EMAIL`, `CANOPY_TRANSCRIPT_MAX_BYTES` | A |
| `apps/canopy/client.py` (modify) | Outbound canopy HTTP. Adds `get`, `send_message`, `get_turn`, `list_unclaimable`, `stop_session` | A/B |
| `apps/canopy/run_dispatch.py` (new) | The seam. `dispatch_turn(assistant_message_id)` — ensure canopy session, enqueue turn, record ids | A |
| `apps/sessions/models.py` (modify) | `Session.canopy_session_id`, `Message.canopy_turn_id`, `IngestUpload.source`/`canopy_turn_ids` | A/C |
| `apps/sessions/migrations/0010_canopy_run_execution.py` (new) | The four fields above + backfill of `IngestUpload.source="local"` | A |
| `apps/canopy/run_state.py` (new) | `reconcile_session(session)` + `execution_state(session)` — canopy turn status → an ace-web run state, including the two no-runner states | B |
| `apps/canopy/management/commands/reconcile_canopy_runs.py` (new) | Batch reconcile, for the deploy hook and cron | B |
| `apps/sessions/api.py` (modify) | Swap 2 call sites; add `GET /{slug}/execution`; route `/structure` through the transcript source | A/B/C |
| `apps/opps/api.py` (modify) | Swap 1 call site; enrich run dicts with `execution` | A/B |
| `apps/canopy/transcripts.py` (new) | `fetch_turn_transcript(turn_id, *, bearer)` — the streaming, gzip-trap-proof reader | C |
| `apps/ingest/sources.py` (new) | `session_raw_jsonl(session) -> bytes | None` — resolves local blob vs canopy transcript | C |
| `apps/ingest/live_ingest.py` (modify) | `store_session_transcript` gains a `source` + `turn_ids` parameter | C |
| `frontend/src/canopy/runState.ts` (new) | `RunExecutionState` type + label/tone mapping | B |
| `frontend/src/components/opps/RunExecutionBadge.tsx` (new) | Renders the state | B |
| `frontend/src/components/views/hierarchy/OppRunsList.tsx` (modify) | Stop rendering an unclaimable run as "queued" | B |
| `apps/slack/run_starter.py` (modify) | Honest messaging + real dispatch + Drive-client fix | D |

---

# PR A — the dispatch seam (`feat/canopy-run-dispatch`)

Branch off `origin/main`. Ships inert: `CANOPY_RUN_EXECUTION` defaults `False`, so every call site keeps spawning the subprocess exactly as today.

---

### Task 1: Settings + persistence for the canopy linkage

**Files:**
- Modify: `config/settings/base.py` (after the existing canopy block at lines 288-296)
- Modify: `apps/sessions/models.py` (`Session` around line 88, `Message` around line 289)
- Create: `apps/sessions/migrations/0010_canopy_run_execution.py`
- Test: `apps/sessions/tests/test_models.py` (append)

**Interfaces:**
- Produces: `settings.CANOPY_RUN_EXECUTION: bool`, `settings.CANOPY_RUN_ACTOR_FALLBACK_EMAIL: str`; `Session.canopy_session_id: str`, `Message.canopy_turn_id: str`.

- [ ] **Step 1: Settings.** In `config/settings/base.py`, directly below `CANOPY_AGENT_SLUG` (line 296):

```python
# Run execution on canopy's harness (spec: canopy-web
# docs/superpowers/specs/2026-07-26-run-execution-convergence-design.md).
# OFF by default and it must stay off until a SESSION-CAPABLE canopy runner
# exists: with none online, every enqueued turn sits QUEUED forever, so
# flipping this on takes ACE runs from "works" to "nothing runs".
CANOPY_RUN_EXECUTION = env.bool("CANOPY_RUN_EXECUTION", default=False)
# Whose canopy identity a run acts as when the owning ace-web user's email is
# not delegable (canopy's token-exchange 403s a domain outside the app
# credential's allowed_delegation_domains). Empty = no fallback: dispatch
# fails loudly rather than silently attributing one human's run to another.
CANOPY_RUN_ACTOR_FALLBACK_EMAIL = env("CANOPY_RUN_ACTOR_FALLBACK_EMAIL", default="")
```

- [ ] **Step 2: Write the failing tests.** Append to `apps/sessions/tests/test_models.py`:

```python
def test_session_carries_canopy_session_id(django_user_model):
    user = django_user_model.objects.create_user(email="owner@example.com")
    s = Session.create_with_owner(owner=user, title="t", opp_slug="o", opp_run_id="r")
    assert s.canopy_session_id == ""          # default: not yet dispatched
    s.canopy_session_id = "9f1c0e2a-0000-4000-8000-000000000001"
    s.save(update_fields=["canopy_session_id"])
    s.refresh_from_db()
    assert s.canopy_session_id == "9f1c0e2a-0000-4000-8000-000000000001"


def test_message_carries_canopy_turn_id(django_user_model):
    user = django_user_model.objects.create_user(email="owner2@example.com")
    s = Session.create_with_owner(owner=user, title="t")
    m = Message.objects.create(
        session=s, turn_index=0, role="assistant", content={"text": ""}, status="pending",
    )
    assert m.canopy_turn_id == ""
    m.canopy_turn_id = "9f1c0e2a-0000-4000-8000-000000000002"
    m.save(update_fields=["canopy_turn_id"])
    assert Message.objects.filter(canopy_turn_id=m.canopy_turn_id).count() == 1
```

- [ ] **Step 3: Run them, confirm they fail.**

Run: `uv run pytest apps/sessions/tests/test_models.py -k canopy -v`
Expected: FAIL — `AttributeError` / `FieldError: Cannot resolve keyword 'canopy_turn_id'`.

- [ ] **Step 4: Add the fields.** In `apps/sessions/models.py`, in `Session` immediately after `opp_step_skill` (line 88):

```python
    # The canopy Session this opp-run executes in (spec 2026-07-26). One
    # canopy Session per ace-web Session, which is already 1:1 with an
    # opp-run. Targeting the SESSION and not the agent is load-bearing:
    # canopy's one_executing_turn_per_agent constraint would serialize every
    # ACE run in the fleet to one at a time; one_executing_turn_per_session
    # matches ace's real shape (one turn per run, many runs at once).
    # Empty = this run has never been dispatched to canopy.
    canopy_session_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
```

In `Message`, immediately after `status` (line 288):

```python
    # The canopy Turn this assistant message is executed by (spec 2026-07-26).
    # ace-web owns this mapping because canopy's send route builds its own
    # origin_ref and takes none from the caller — see run_dispatch.py.
    canopy_turn_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
```

- [ ] **Step 5: Generate the migration.**

Run: `uv run python manage.py makemigrations ace_sessions --name canopy_run_execution`
Expected: creates `apps/sessions/migrations/0010_canopy_run_execution.py` with two `AddField` operations. Open it and confirm it contains no `RemoveField` and no `AlterField` on any existing column.

- [ ] **Step 6: Run the tests, confirm they pass.**

Run: `uv run pytest apps/sessions/tests/test_models.py -k canopy -v`
Expected: 2 passed.

- [ ] **Step 7: Commit.**

```bash
git add config/settings/base.py apps/sessions/models.py apps/sessions/migrations/0010_canopy_run_execution.py apps/sessions/tests/test_models.py docs/plans/2026-07-26-run-convergence-ace-side.md
git commit -m "feat(canopy): persist the canopy session/turn linkage on run records

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Canopy client — the run-execution calls

**Files:**
- Modify: `apps/canopy/client.py`
- Test: `tests/test_canopy_run_client.py` (create)

**Interfaces:**
- Consumes: `settings.CANOPY_BASE_URL`, `settings.CANOPY_APP_CREDENTIAL`, `settings.CANOPY_WORKSPACE`, `settings.CANOPY_AGENT_SLUG`; the existing `_post(path, payload, *, bearer)` and `exchange_token(email, ttl=3600)`.
- Produces: `client._get(path, *, bearer) -> dict | list`, `client.create_run_session(user_token, *, title, metadata) -> dict`, `client.send_message(user_token, session_id, *, text, client_id) -> dict`, `client.get_turn(user_token, turn_id) -> dict`, `client.list_unclaimable(user_token) -> list[dict]`, `client.stop_session(user_token, session_id) -> dict`.

The canopy contract, read off canopy-web `main` (do not re-derive it — these are the exact shapes):

| Call | canopy route | Body | Response |
|---|---|---|---|
| create session | `POST /api/w/{ws}/canopy-sessions/` | `{"agent_slug","title","metadata"}` | `SessionOut` — `id` is a UUID string |
| send | `POST /api/canopy-sessions/{id}/send` | `{"text","client_id"}` | `SendOut` — `{"turn_id": str \| null, "message": {...}}` |
| get turn | `GET /api/harness/turns/{turn_id}` | — | `TurnOut` — `status ∈ {queued,claimed,running,needs_human,done,failed,lost,missed,cancelled}`, plus `result_note`, `created_at`, `finished_at` |
| unclaimable | `GET /api/harness/turns/unclaimable` | — | `list[UnclaimableTurnOut]` — `{"turn_id","target","prompt","created_at","reason","kind"}`, `kind ∈ {"config","offline"}` |
| stop | `POST /api/canopy-sessions/{id}/stop` | `{}` | `{"cancelled": bool}` |

**`SendIn` has no `origin_ref` field.** The spec says `origin_ref` carries `{opp_slug, run_id, step_skill}`; that is true of canopy's *internal* `services.enqueue_turn`, but the HTTP send route builds its own `origin_ref = {"thread_key", "chat_session_id"}` (`apps/canopy_sessions/services.py:636`) and accepts none from the caller. So ace-web stamps the opp linkage on the **session metadata** instead — which canopy already supports and already filters on (`metadata__opp_slug`, `metadata__opp_run_id`, `metadata__origin_key`, `apps/canopy_sessions/api.py:186-195`) — and keeps the per-turn `step_skill` correlation locally on `Message.canopy_turn_id`. This is a deliberate, documented divergence from the spec's wording, not an oversight; a one-field canopy follow-up (`SendIn.origin_ref: dict = {}`) would close it and is worth filing, but nothing here blocks on it.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_canopy_run_client.py`:

```python
"""apps.canopy.client — the run-execution calls (spec 2026-07-26)."""

import io
import json
from unittest import mock

import pytest
from django.test import override_settings

from apps.canopy import client

ENABLED = dict(
    CANOPY_BASE_URL="http://canopy.test",
    CANOPY_APP_CREDENTIAL="secret-cred",
    CANOPY_WORKSPACE="connect",
    CANOPY_AGENT_SLUG="ace",
)


class _Resp(io.BytesIO):
    """Minimal urlopen context-manager stand-in."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen(payload):
    return mock.patch(
        "apps.canopy.client.urllib.request.urlopen",
        return_value=_Resp(json.dumps(payload).encode()),
    )


@override_settings(**ENABLED)
def test_create_run_session_targets_the_workspace_route_and_agent():
    with _urlopen({"id": "sess-1"}) as opened:
        out = client.create_run_session(
            "usertok", title="seeded-run: o/r", metadata={"opp_slug": "o"},
        )
    assert out["id"] == "sess-1"
    req = opened.call_args.args[0]
    assert req.full_url == "http://canopy.test/api/w/connect/canopy-sessions/"
    body = json.loads(req.data)
    assert body["agent_slug"] == "ace"
    assert body["metadata"] == {"opp_slug": "o"}
    assert req.get_header("Authorization") == "Bearer usertok"


@override_settings(**ENABLED)
def test_send_message_posts_text_and_client_id_and_returns_turn_id():
    with _urlopen({"turn_id": "turn-1", "message": {"id": 7}}) as opened:
        out = client.send_message("usertok", "sess-1", text="/ace:run o/r", client_id="k1")
    assert out["turn_id"] == "turn-1"
    req = opened.call_args.args[0]
    assert req.full_url == "http://canopy.test/api/canopy-sessions/sess-1/send"
    assert json.loads(req.data) == {"text": "/ace:run o/r", "client_id": "k1"}


@override_settings(**ENABLED)
def test_get_turn_is_a_GET_with_the_bearer():
    with _urlopen({"id": "turn-1", "status": "queued"}) as opened:
        out = client.get_turn("usertok", "turn-1")
    assert out["status"] == "queued"
    req = opened.call_args.args[0]
    assert req.get_method() == "GET"
    assert req.full_url == "http://canopy.test/api/harness/turns/turn-1"


@override_settings(**ENABLED)
def test_list_unclaimable_returns_the_rows_verbatim():
    rows = [{"turn_id": "turn-1", "kind": "config", "reason": "no runner ...",
             "target": "session", "prompt": "", "created_at": "2026-07-26T00:00:00Z"}]
    with _urlopen(rows) as opened:
        out = client.list_unclaimable("usertok")
    assert out == rows
    assert opened.call_args.args[0].full_url == "http://canopy.test/api/harness/turns/unclaimable"


@override_settings(**ENABLED)
def test_http_error_becomes_canopy_error():
    import urllib.error

    err = urllib.error.HTTPError("u", 403, "forbidden", {}, io.BytesIO(b"nope"))
    with mock.patch("apps.canopy.client.urllib.request.urlopen", side_effect=err):
        with pytest.raises(client.CanopyError) as exc:
            client.get_turn("usertok", "turn-1")
    assert exc.value.status == 403
```

- [ ] **Step 2: Run them, confirm they fail.**

Run: `uv run pytest tests/test_canopy_run_client.py -v`
Expected: FAIL — `AttributeError: module 'apps.canopy.client' has no attribute 'create_run_session'`.

- [ ] **Step 3: Implement.** Append to `apps/canopy/client.py` (keep the existing `_post` and `exchange_token`/`create_session` untouched — `create_session` is the browser chat path and has different metadata rules):

```python
def _get(path: str, *, bearer: str):
    req = urllib.request.Request(
        f"{settings.CANOPY_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {bearer}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise CanopyError(exc.code, exc.read().decode(errors="replace")[:300]) from exc
    except urllib.error.URLError as exc:
        raise CanopyError(502, str(exc.reason)) from exc


def create_run_session(user_token: str, *, title: str, metadata: dict) -> dict:
    """Create the canopy Session an opp-run executes in.

    Separate from `create_session` (the browser chat path) on purpose: a run's
    metadata is stamped by the server-side dispatcher, and keeping the two
    callers apart stops one's metadata rules leaking into the other.
    """
    return _post(
        f"/api/w/{settings.CANOPY_WORKSPACE}/canopy-sessions/",
        {"agent_slug": settings.CANOPY_AGENT_SLUG, "title": title, "metadata": metadata},
        bearer=user_token,
    )


def send_message(user_token: str, session_id: str, *, text: str, client_id: str) -> dict:
    """Enqueue a session-targeted Turn. `client_id` makes a retried send collapse
    onto the SAME user Message + Turn (canopy send_message's idempotency nonce),
    which is what makes dispatch safe to retry."""
    return _post(
        f"/api/canopy-sessions/{session_id}/send",
        {"text": text, "client_id": client_id},
        bearer=user_token,
    )


def get_turn(user_token: str, turn_id: str) -> dict:
    return _get(f"/api/harness/turns/{turn_id}", bearer=user_token)


def list_unclaimable(user_token: str) -> list:
    """Queued turns canopy says no runner can claim, after a 150s grace.
    `kind` is "config" (nothing declares this target) or "offline" (something
    does, none reachable). See run_state.py for why `kind` is advisory."""
    return _get("/api/harness/turns/unclaimable", bearer=user_token)


def stop_session(user_token: str, session_id: str) -> dict:
    """Cancel every non-terminal turn on a session. Used by resume: an ace-web
    resume declares the previous turn dead, and canopy must be told, or the
    stale turn keeps holding one_executing_turn_per_session."""
    return _post(f"/api/canopy-sessions/{session_id}/stop", {}, bearer=user_token)
```

- [ ] **Step 4: Run the tests, confirm they pass.**

Run: `uv run pytest tests/test_canopy_run_client.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit.**

```bash
git add apps/canopy/client.py tests/test_canopy_run_client.py
git commit -m "feat(canopy): client calls for session create, send, turn read, unclaimable, stop

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `dispatch_turn` — the seam

**Files:**
- Create: `apps/canopy/run_dispatch.py`
- Test: `tests/test_canopy_run_dispatch.py` (create)

**Interfaces:**
- Consumes: `client.exchange_token`, `client.create_run_session`, `client.send_message`, `client.stop_session`, `Session.canopy_session_id`, `Message.canopy_turn_id`.
- Produces: `run_dispatch.enabled() -> bool`; `run_dispatch.dispatch_turn(assistant_message_id: int) -> str` (returns the canopy turn id, or `""` when disabled); `run_dispatch.DispatchError(Exception)` with `.detail: str`.

Design notes an implementer must not re-derive:

1. **Actor identity.** canopy's `POST /api/auth/token-exchange` needs an `acting_as_email` whose domain is in the app credential's `allowed_delegation_domains` **and** in canopy's login allowlist. ace-web deliberately has **no** domain filter ("workspace membership is the access-control gate", `CLAUDE.md`), so an ace-web user can perfectly well hold an email canopy will refuse. Act as `session.owner.email` (always populated — the FK is `PROTECT`), fall back to `settings.CANOPY_RUN_ACTOR_FALLBACK_EMAIL` only if set, and otherwise fail loudly. Never silently attribute one human's run to another.
2. **Idempotency.** `client_id` is `f"acerun:{assistant_message_id}"`. canopy's `send_message` collapses a repeat onto the same Message + Turn, so a retried dispatch cannot double-enqueue.
3. **Resume must stop the old turn first.** `resume_session_run` (`apps/sessions/api.py:241`) exists precisely because the previous turn is dead. On canopy the previous turn may still be `QUEUED` or executing and holds `one_executing_turn_per_session`. Call `stop_session` before sending, and only when the session already has a `canopy_session_id`.
4. **Never leave the run silently un-dispatched.** `start_turn_subprocess` is fire-and-forget with no failure signal (`turn_driver.py:448`) — a `Popen` failure leaves the assistant Message `pending` forever. Do not reproduce that. On failure, mark the Message `error` with a `canopy-dispatch:` prefix so it is distinguishable from an execution error, and re-raise.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_canopy_run_dispatch.py`:

```python
"""apps.canopy.run_dispatch — enqueue a canopy Turn instead of spawning claude -p."""

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.canopy import run_dispatch
from apps.sessions.models import Message, Session

User = get_user_model()
pytestmark = pytest.mark.django_db

ON = dict(
    CANOPY_BASE_URL="http://canopy.test",
    CANOPY_APP_CREDENTIAL="secret-cred",
    CANOPY_WORKSPACE="connect",
    CANOPY_AGENT_SLUG="ace",
    CANOPY_RUN_EXECUTION=True,
)


def _run(**kw):
    user = User.objects.create_user(email="runner@dimagi.com")
    session = Session.create_with_owner(
        owner=user, title="seeded-run: opp-a/run-1", backend_kind="cli",
        status="active", source="web", opp_slug="opp-a", opp_run_id="run-1", **kw,
    )
    Message.objects.create(
        session=session, turn_index=0, role="user", sender_user=user,
        content={"text": "/ace:run opp-a/run-1"}, plaintext="/ace:run opp-a/run-1",
        status="complete",
    )
    assistant = Message.objects.create(
        session=session, turn_index=1, role="assistant", content={"text": ""}, status="pending",
    )
    return session, assistant


def _patched(send_return=None):
    return (
        mock.patch("apps.canopy.client.exchange_token", return_value={"token": "usertok"}),
        mock.patch("apps.canopy.client.create_run_session", return_value={"id": "sess-9"}),
        mock.patch(
            "apps.canopy.client.send_message",
            return_value=send_return or {"turn_id": "turn-9", "message": {}},
        ),
        mock.patch("apps.canopy.client.stop_session", return_value={"cancelled": False}),
    )


def test_disabled_by_default_is_a_noop():
    session, assistant = _run()
    assert run_dispatch.enabled() is False
    assert run_dispatch.dispatch_turn(assistant.id) == ""
    session.refresh_from_db()
    assert session.canopy_session_id == ""


@override_settings(**ON)
def test_creates_one_session_per_opp_run_with_opp_metadata():
    session, assistant = _run()
    ex, create, send, stop = _patched()
    with ex, create as create_m, send, stop:
        run_dispatch.dispatch_turn(assistant.id)
    session.refresh_from_db()
    assert session.canopy_session_id == "sess-9"
    meta = create_m.call_args.kwargs["metadata"]
    assert meta["source"] == "ace-web"
    assert meta["opp_slug"] == "opp-a"
    assert meta["opp_run_id"] == "run-1"


@override_settings(**ON)
def test_reuses_the_existing_canopy_session_and_stops_its_stale_turn():
    session, assistant = _run(canopy_session_id="sess-existing")
    ex, create, send, stop = _patched()
    with ex, create as create_m, send as send_m, stop as stop_m:
        run_dispatch.dispatch_turn(assistant.id)
    create_m.assert_not_called()
    stop_m.assert_called_once()
    assert send_m.call_args.args[1] == "sess-existing"


@override_settings(**ON)
def test_records_the_turn_id_on_the_assistant_message():
    session, assistant = _run()
    ex, create, send, stop = _patched()
    with ex, create, send, stop:
        turn_id = run_dispatch.dispatch_turn(assistant.id)
    assistant.refresh_from_db()
    assert turn_id == "turn-9"
    assert assistant.canopy_turn_id == "turn-9"
    assert assistant.status == "pending"


@override_settings(**ON)
def test_sends_the_user_turns_text_not_an_empty_prompt():
    session, assistant = _run()
    ex, create, send, stop = _patched()
    with ex, create, send as send_m, stop:
        run_dispatch.dispatch_turn(assistant.id)
    assert send_m.call_args.kwargs["text"] == "/ace:run opp-a/run-1"
    assert send_m.call_args.kwargs["client_id"] == f"acerun:{assistant.id}"


@override_settings(**ON)
def test_dispatch_failure_marks_the_message_error_and_raises():
    from apps.canopy.client import CanopyError

    session, assistant = _run()
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(403, "nope")):
        with pytest.raises(run_dispatch.DispatchError):
            run_dispatch.dispatch_turn(assistant.id)
    assistant.refresh_from_db()
    assert assistant.status == "error"
    assert assistant.error_detail.startswith("canopy-dispatch:")


@override_settings(**ON)
def test_a_null_turn_id_from_canopy_is_a_dispatch_failure():
    session, assistant = _run()
    ex, create, send, stop = _patched(send_return={"turn_id": None, "message": {}})
    with ex, create, send, stop:
        with pytest.raises(run_dispatch.DispatchError):
            run_dispatch.dispatch_turn(assistant.id)
    assistant.refresh_from_db()
    assert assistant.status == "error"
```

- [ ] **Step 2: Run them, confirm they fail.**

Run: `uv run pytest tests/test_canopy_run_dispatch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.canopy.run_dispatch'`.

- [ ] **Step 3: Implement.** Create `apps/canopy/run_dispatch.py`:

```python
"""Enqueue an ACE run onto canopy's harness instead of spawning `claude -p`.

The drop-in replacement for `apps.sessions.turn_driver.start_turn_subprocess`
(spec: canopy-web docs/superpowers/specs/2026-07-26-run-execution-convergence-
design.md, item 4). Same call shape — one assistant-Message id — so the three
production call sites change by one line each.

Turns target the canopy SESSION, never the agent. `one_executing_turn_per_agent`
is a unique constraint on the agent for claimed/running turns, so `Turn(agent=ace)`
would serialize every ACE run in the fleet to one at a time;
`one_executing_turn_per_session` matches ace's real shape (one turn at a time
within a run, many runs at once). `Turn.target` resolves `chat_session.agent.slug`,
so ACE still displays as "ace" everywhere in canopy.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from . import client

log = logging.getLogger(__name__)


class DispatchError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def enabled() -> bool:
    return bool(
        settings.CANOPY_RUN_EXECUTION
        and settings.CANOPY_BASE_URL
        and settings.CANOPY_APP_CREDENTIAL
    )


def _actor_email(session) -> str:
    """Whose canopy identity this run acts as. The owner, or the configured
    fallback — never a guess. canopy's token-exchange 403s an email outside the
    app credential's allowed_delegation_domains, and ace-web has no domain
    filter of its own, so a refusal here is a real and reachable case."""
    email = (getattr(session.owner, "email", "") or "").strip()
    if email:
        return email
    fallback = (settings.CANOPY_RUN_ACTOR_FALLBACK_EMAIL or "").strip()
    if fallback:
        return fallback
    raise DispatchError("no canopy actor: session owner has no email and no fallback is set")


def _run_metadata(session) -> dict:
    """The opaque bag canopy filters its session list on. `origin_key` mirrors
    apps/canopy/api.py's server-side derivation exactly — it is what scopes
    canopy's list to ONE ace workspace, so it must not drift."""
    meta = {"source": "ace-web"}
    if session.workspace_id:
        meta["origin_key"] = f"ace-web:{session.workspace.slug}"
    if session.opp_slug:
        meta["opp_slug"] = session.opp_slug
    if session.opp_run_id:
        meta["opp_run_id"] = session.opp_run_id
    if session.opp_step_skill:
        meta["opp_step_skill"] = session.opp_step_skill
    return meta


def _prompt_for(assistant_message) -> str:
    """The last completed user turn before this assistant placeholder — the same
    text `turn_driver._load_last_user_text` feeds the subprocess."""
    from apps.sessions.models import Message

    user_msg = (
        Message.objects.filter(
            session_id=assistant_message.session_id,
            role="user",
            turn_index__lt=assistant_message.turn_index,
        )
        .order_by("-turn_index")
        .first()
    )
    return user_msg.plaintext if user_msg else ""


def _fail(assistant_message, detail: str) -> None:
    """Never leave a run silently un-dispatched. `start_turn_subprocess` did
    exactly that on a Popen failure (fire-and-forget, no signal) and the message
    sat `pending` forever. The `canopy-dispatch:` prefix keeps a dispatch failure
    distinguishable from an execution failure — and, deliberately, does NOT start
    with "cancelled", so `Session.resumable_after_deploy` will not treat it as a
    deploy casualty and re-resume it in a loop."""
    from apps.sessions.models import Message

    Message.objects.filter(pk=assistant_message.pk).update(
        status="error", error_detail=f"canopy-dispatch: {detail}", completed_at=timezone.now(),
    )


def dispatch_turn(assistant_message_id: int) -> str:
    """Enqueue the canopy Turn that executes this assistant turn.

    Returns the canopy turn id, or "" when run execution is disabled (in which
    case the caller keeps its legacy subprocess path). Raises DispatchError on
    any failure, having first marked the assistant message errored.
    """
    if not enabled():
        return ""

    from apps.sessions.models import Message, Session

    assistant = (
        Message.objects.select_related("session", "session__owner", "session__workspace")
        .filter(pk=assistant_message_id)
        .first()
    )
    if assistant is None:
        raise DispatchError(f"assistant message {assistant_message_id} not found")
    session = assistant.session

    try:
        token = client.exchange_token(_actor_email(session), ttl=3600)["token"]

        canopy_session_id = session.canopy_session_id
        if canopy_session_id:
            # A resume declares the previous turn dead. Tell canopy, or the stale
            # turn keeps holding one_executing_turn_per_session and this send
            # queues behind a turn that will never finish.
            try:
                client.stop_session(token, canopy_session_id)
            except client.CanopyError:
                log.warning("canopy stop failed for session %s; continuing", canopy_session_id)
        else:
            created = client.create_run_session(
                token,
                title=session.title or f"ace-run: {session.opp_slug}/{session.opp_run_id}",
                metadata=_run_metadata(session),
            )
            canopy_session_id = str(created["id"])
            Session.objects.filter(pk=session.pk).update(canopy_session_id=canopy_session_id)

        sent = client.send_message(
            token,
            canopy_session_id,
            text=_prompt_for(assistant),
            client_id=f"acerun:{assistant.pk}",
        )
        turn_id = sent.get("turn_id")
        if not turn_id:
            raise DispatchError("canopy accepted the send but returned no turn_id")
    except DispatchError as exc:
        _fail(assistant, exc.detail)
        raise
    except client.CanopyError as exc:
        _fail(assistant, f"{exc.status}: {exc.detail}")
        raise DispatchError(f"canopy {exc.status}: {exc.detail}") from exc

    Message.objects.filter(pk=assistant.pk).update(canopy_turn_id=str(turn_id))
    return str(turn_id)
```

- [ ] **Step 4: Run the tests, confirm they pass.**

Run: `uv run pytest tests/test_canopy_run_dispatch.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit.**

```bash
git add apps/canopy/run_dispatch.py tests/test_canopy_run_dispatch.py
git commit -m "feat(canopy): dispatch_turn — enqueue a session-targeted canopy Turn

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Swap the three call sites

**Files:**
- Modify: `apps/opps/api.py:1886` + `:1912` (`seeded_run`)
- Modify: `apps/sessions/api.py:309` + `:323` (`resume_interrupted`), `:336` + `:347` (`resume_run`)
- Create: `apps/canopy/run_dispatch.py::start_turn` (a tiny router — added in Step 3 below)
- Test: `tests/test_canopy_run_dispatch.py` (append), `apps/opps/tests/test_api.py` (append), `apps/sessions/tests/test_api.py` (append)

**Interfaces:**
- Consumes: `run_dispatch.dispatch_turn`, `turn_driver.start_turn_subprocess`.
- Produces: `run_dispatch.start_turn(assistant_message_id: int) -> None` — the single function all three call sites call. Existing tests monkeypatch `apps.sessions.turn_driver.start_turn_subprocess` (`apps/opps/tests/test_api.py:1677,1705,1726,1746`; `apps/sessions/tests/test_api.py:574,599,609,642`); `start_turn` calls that symbol through its module, so those patches keep working unchanged.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_canopy_run_dispatch.py`:

```python
def test_start_turn_spawns_the_subprocess_when_disabled():
    session, assistant = _run()
    with mock.patch("apps.sessions.turn_driver.start_turn_subprocess") as spawn:
        run_dispatch.start_turn(assistant.id)
    spawn.assert_called_once_with(assistant.id)


@override_settings(**ON)
def test_start_turn_dispatches_to_canopy_and_never_spawns_when_enabled():
    session, assistant = _run()
    ex, create, send, stop = _patched()
    with mock.patch("apps.sessions.turn_driver.start_turn_subprocess") as spawn:
        with ex, create, send, stop:
            run_dispatch.start_turn(assistant.id)
    spawn.assert_not_called()
    assistant.refresh_from_db()
    assert assistant.canopy_turn_id == "turn-9"
```

- [ ] **Step 2: Run them, confirm they fail.**

Run: `uv run pytest tests/test_canopy_run_dispatch.py -k start_turn -v`
Expected: FAIL — `AttributeError: module 'apps.canopy.run_dispatch' has no attribute 'start_turn'`.

- [ ] **Step 3: Add `start_turn`.** Append to `apps/canopy/run_dispatch.py`:

```python
def start_turn(assistant_message_id: int) -> None:
    """The ONE entry point every run caller uses. Routes to canopy when run
    execution is on, and to the legacy in-process subprocess when it is not.

    Imported through the module (not `from ... import start_turn_subprocess`)
    so the existing monkeypatches on
    `apps.sessions.turn_driver.start_turn_subprocess` keep working.
    """
    if enabled():
        dispatch_turn(assistant_message_id)
        return
    from apps.sessions import turn_driver

    turn_driver.start_turn_subprocess(assistant_message_id)
```

- [ ] **Step 4: Swap `seeded_run`.** In `apps/opps/api.py`, replace line 1886:

```python
    from apps.sessions.turn_driver import start_turn_subprocess
```

with:

```python
    from apps.canopy.run_dispatch import start_turn
```

and replace lines 1910-1912:

```python
    # Drive the turn out-of-band in a detached process (faithful, openable, and
    # decoupled from this request's loop). See ace-web#585.
    start_turn_subprocess(result["assistant_message_id"])
```

with:

```python
    # Execute the turn. With CANOPY_RUN_EXECUTION on this enqueues a
    # session-targeted canopy Turn; with it off it spawns the legacy detached
    # `manage.py drive_turn` process (ace-web#585). Either way the run is
    # decoupled from this request's event loop.
    start_turn(result["assistant_message_id"])
```

- [ ] **Step 5: Swap the two resume sites.** In `apps/sessions/api.py`, replace line 309 (`resume_interrupted`) and line 336 (`resume_run`), each currently `from apps.sessions.turn_driver import start_turn_subprocess`, with:

```python
    from apps.canopy.run_dispatch import start_turn
```

Then replace the call at line 323 (inside the `for s in candidates:` loop):

```python
            start_turn_subprocess(res["assistant_message_id"])
```

with:

```python
            start_turn(res["assistant_message_id"])
```

and the call at line 347:

```python
    start_turn_subprocess(res["assistant_message_id"])
```

with:

```python
    start_turn(res["assistant_message_id"])
```

- [ ] **Step 6: Add a per-call-site test.** Append to `apps/opps/tests/test_api.py` (near the existing seeded-run tests around line 1677):

```python
def test_seeded_run_routes_through_the_canopy_dispatch_seam(monkeypatch, ...):
    """The route must call run_dispatch.start_turn, not the subprocess directly —
    otherwise flipping CANOPY_RUN_EXECUTION has no effect on the seeded run."""
    called = []
    monkeypatch.setattr("apps.canopy.run_dispatch.start_turn", lambda mid: called.append(mid))
    monkeypatch.setattr(
        "apps.opps.api.seed_run_for_opp",
        lambda *a, **k: {"session_slug": "s", "assistant_message_id": 4242, "run_id": "r"},
    )
    # ... issue the POST exactly as the neighbouring seeded-run tests do ...
    assert called == [4242]
```

Fill the `...` by copying the client/auth/workspace setup from the adjacent seeded-run test in the same file — do not invent a new fixture shape.

Add the mirror-image test for `resume_run` in `apps/sessions/tests/test_api.py`, patching `apps.canopy.run_dispatch.start_turn` and asserting it receives the assistant message id that `resume_session_run` returned.

- [ ] **Step 7: Run the full suite.**

Run: `uv run pytest`
Expected: all green, including the eight pre-existing `start_turn_subprocess` monkeypatch tests — `start_turn` reaches that symbol through the module, so they still intercept it.

- [ ] **Step 8: Regenerate types and commit.**

```bash
cd frontend && npm run gen:api:local && cd ..
git add apps/opps/api.py apps/sessions/api.py apps/canopy/run_dispatch.py tests/test_canopy_run_dispatch.py apps/opps/tests/test_api.py apps/sessions/tests/test_api.py frontend/src/api/generated.ts
git commit -m "feat(canopy): route seeded_run + both resume paths through the dispatch seam

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 9: Open PR A.**

```bash
git push -u origin feat/canopy-run-dispatch
gh pr create --title "feat(canopy): enqueue ACE runs onto canopy's harness (dark, flag-gated)" --body "$(cat <<'EOF'
Item 4 of the run-execution convergence spec. Ships DARK: `CANOPY_RUN_EXECUTION`
defaults False, so all three run call sites keep spawning the legacy subprocess.

- One canopy Session per ace-web Session (already 1:1 with an opp-run); Turns
  target the SESSION, never the agent (`one_executing_turn_per_agent` would
  serialize the whole ACE fleet).
- `Session.canopy_session_id` + `Message.canopy_turn_id` carry the linkage.
- Three call sites now go through `run_dispatch.start_turn`.

`apps/sessions`' Session/Message/SessionParticipant models are the execution
record for programmatic runs, not legacy chat — nothing here deletes them.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
gh pr merge --auto --squash
```

---

# PR B — "no runner available" as a first-class run state (`feat/canopy-run-state`)

Branch off PR A's merge. This is Item 6. **With no cloud runner it is the normal path, not an edge case** — so it is modelled as a state a run can be in, sitting alongside `running` and `done`, never as an error toast.

The defect it fixes is concrete. `frontend/src/components/views/hierarchy/OppRunsList.tsx::ProgressLabel` renders, for a run with nothing done yet, the literal string `"queued"` — identical for "about to start" and "no runner will ever take this". Today an enqueued turn with no runner sits `QUEUED` in canopy silently and forever; nothing auto-fails it.

---

### Task 5: Map a canopy turn to a run execution state

**Files:**
- Create: `apps/canopy/run_state.py`
- Test: `tests/test_canopy_run_state.py` (create)

**Interfaces:**
- Consumes: `client.get_turn`, `client.list_unclaimable`, `client.exchange_token`, `Message.canopy_turn_id`.
- Produces:
  ```python
  STATES = (
      "not_dispatched",       # no canopy turn — legacy/local execution, or never sent
      "queued",               # canopy QUEUED, inside the 150s grace
      "no_runner_configured", # unclaimable, kind="config"
      "waiting_for_runner",   # unclaimable, kind="offline"
      "running",              # canopy CLAIMED / RUNNING / NEEDS_HUMAN
      "done", "failed", "cancelled", "lost", "missed",
      "dispatch_failed",      # ace-web never got a turn id
      "unknown",              # canopy unreachable — say so, never guess "running"
  )
  run_state.execution_state(session) -> dict
      # {"state": str, "detail": str, "canopy_turn_id": str, "canopy_session_id": str}
  ```

Two facts about `unclaimable` an implementer must know, because they change what the UI may claim:

1. **`kind` is advisory, not authoritative.** `unclaimable_queued_turns` (canopy `apps/harness/services.py:288`) computes "could any runner ever take this?" from `Runner.objects.filter(paired_by=user)` — runners the *calling user personally paired*. ace-web's delegated user has paired none. ace-web's own frontend already documents this for the runner fleet (`frontend/src/canopy/api.ts`, `listCanopyRunners`: "a delegated ace user typically has paired none, so this usually returns `[]`"). So for ace, `claimable_ever` is empty and **every** unclaimable turn comes back `kind="config"`. Model both states, render both honestly, and do **not** build logic that depends on ever seeing `"offline"`.
2. **The 150s grace is canopy's, not ours.** `UNCLAIMABLE_GRACE = 150s`. A turn younger than that is simply absent from the list. Do not add a second timer on this side; a run under 150s old with a `QUEUED` turn is `"queued"`, full stop.

- [ ] **Step 1: Write the failing tests.** Create `tests/test_canopy_run_state.py`:

```python
"""apps.canopy.run_state — a canopy Turn's status as an ACE run state."""

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.canopy import run_state
from apps.sessions.models import Message, Session

User = get_user_model()
pytestmark = pytest.mark.django_db

ON = dict(
    CANOPY_BASE_URL="http://canopy.test", CANOPY_APP_CREDENTIAL="c",
    CANOPY_WORKSPACE="connect", CANOPY_AGENT_SLUG="ace", CANOPY_RUN_EXECUTION=True,
)


def _session_with_turn(turn_id="turn-1"):
    user = User.objects.create_user(email="o@dimagi.com")
    s = Session.create_with_owner(
        owner=user, title="t", opp_slug="o", opp_run_id="r",
        canopy_session_id="sess-1" if turn_id else "",
    )
    Message.objects.create(
        session=s, turn_index=0, role="assistant", content={"text": ""},
        status="pending", canopy_turn_id=turn_id,
    )
    return s


def _canopy(turn=None, unclaimable=()):
    return (
        mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}),
        mock.patch("apps.canopy.client.get_turn", return_value=turn or {"status": "queued"}),
        mock.patch("apps.canopy.client.list_unclaimable", return_value=list(unclaimable)),
    )


@override_settings(**ON)
def test_no_turn_id_is_not_dispatched():
    s = _session_with_turn(turn_id="")
    assert run_state.execution_state(s)["state"] == "not_dispatched"


@override_settings(**ON)
def test_queued_and_not_yet_unclaimable_is_queued():
    s = _session_with_turn()
    ex, get, unc = _canopy(turn={"status": "queued"})
    with ex, get, unc:
        assert run_state.execution_state(s)["state"] == "queued"


@override_settings(**ON)
def test_unclaimable_config_is_no_runner_configured_with_canopys_reason():
    s = _session_with_turn()
    rows = [{"turn_id": "turn-1", "kind": "config", "reason": "no runner can take this session"}]
    ex, get, unc = _canopy(turn={"status": "queued"}, unclaimable=rows)
    with ex, get, unc:
        out = run_state.execution_state(s)
    assert out["state"] == "no_runner_configured"
    assert out["detail"] == "no runner can take this session"


@override_settings(**ON)
def test_unclaimable_offline_is_waiting_for_runner():
    s = _session_with_turn()
    rows = [{"turn_id": "turn-1", "kind": "offline", "reason": "none are reachable right now"}]
    ex, get, unc = _canopy(turn={"status": "queued"}, unclaimable=rows)
    with ex, get, unc:
        assert run_state.execution_state(s)["state"] == "waiting_for_runner"


@override_settings(**ON)
def test_unclaimable_is_only_consulted_for_a_queued_turn():
    """A running turn must never be re-labelled from a stale unclaimable list."""
    s = _session_with_turn()
    rows = [{"turn_id": "turn-1", "kind": "config", "reason": "stale"}]
    ex, get, unc = _canopy(turn={"status": "running"}, unclaimable=rows)
    with ex, get, unc as unc_m:
        assert run_state.execution_state(s)["state"] == "running"
    unc_m.assert_not_called()


@override_settings(**ON)
@pytest.mark.parametrize(
    "canopy_status,expected",
    [("claimed", "running"), ("running", "running"), ("needs_human", "running"),
     ("done", "done"), ("failed", "failed"), ("cancelled", "cancelled"),
     ("lost", "lost"), ("missed", "missed")],
)
def test_terminal_and_executing_statuses_map_through(canopy_status, expected):
    s = _session_with_turn()
    ex, get, unc = _canopy(turn={"status": canopy_status, "result_note": ""})
    with ex, get, unc:
        assert run_state.execution_state(s)["state"] == expected


@override_settings(**ON)
def test_canopy_unreachable_is_unknown_never_running():
    from apps.canopy.client import CanopyError

    s = _session_with_turn()
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(502, "down")):
        out = run_state.execution_state(s)
    assert out["state"] == "unknown"


@override_settings(**ON)
def test_a_dispatch_failed_message_reports_dispatch_failed():
    s = _session_with_turn(turn_id="")
    Message.objects.filter(session=s).update(
        status="error", error_detail="canopy-dispatch: canopy 403: nope",
    )
    assert run_state.execution_state(s)["state"] == "dispatch_failed"
```

- [ ] **Step 2: Run them, confirm they fail.**

Run: `uv run pytest tests/test_canopy_run_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.canopy.run_state'`.

- [ ] **Step 3: Implement.** Create `apps/canopy/run_state.py`:

```python
"""What a run is actually doing, when its execution lives in canopy.

Item 6 of the run-execution convergence spec. With no session-capable cloud
runner online, `no_runner_configured` is the NORMAL state of a freshly
dispatched run — which is exactly why it is a run state and not an error.
Rendering it as "queued" (which is what OppRunsList does today for a run with
no phase yet) makes a run that will never start look like one about to.
"""

from __future__ import annotations

import logging

from django.conf import settings

from . import client

log = logging.getLogger(__name__)

NOT_DISPATCHED = "not_dispatched"
QUEUED = "queued"
NO_RUNNER_CONFIGURED = "no_runner_configured"
WAITING_FOR_RUNNER = "waiting_for_runner"
RUNNING = "running"
DISPATCH_FAILED = "dispatch_failed"
UNKNOWN = "unknown"

STATES = (
    NOT_DISPATCHED, QUEUED, NO_RUNNER_CONFIGURED, WAITING_FOR_RUNNER, RUNNING,
    "done", "failed", "cancelled", "lost", "missed", DISPATCH_FAILED, UNKNOWN,
)

# canopy Turn.status -> our state. `needs_human` folds into RUNNING: the turn is
# claimed and a runner still owns its lease, so it is not stalled on US.
_TURN_STATUS = {
    "queued": QUEUED,
    "claimed": RUNNING,
    "running": RUNNING,
    "needs_human": RUNNING,
    "done": "done",
    "failed": "failed",
    "cancelled": "cancelled",
    "lost": "lost",
    "missed": "missed",
}

DISPATCH_ERROR_PREFIX = "canopy-dispatch:"


def _latest_assistant(session):
    from apps.sessions.models import Message

    return (
        Message.objects.filter(session=session, role="assistant")
        .order_by("-turn_index")
        .first()
    )


def _out(state: str, *, detail: str = "", turn_id: str = "", session_id: str = "") -> dict:
    return {
        "state": state,
        "detail": detail,
        "canopy_turn_id": turn_id,
        "canopy_session_id": session_id,
    }


def execution_state(session) -> dict:
    """The run's execution state, read live from canopy.

    Read-only and side-effect free. Never returns RUNNING on uncertainty: an
    unreachable canopy is UNKNOWN, because "looks like it is working" is the
    exact failure this whole task exists to remove.
    """
    message = _latest_assistant(session)
    if message is None:
        return _out(NOT_DISPATCHED, session_id=session.canopy_session_id)

    if not message.canopy_turn_id:
        detail = message.error_detail or ""
        if message.status == "error" and detail.startswith(DISPATCH_ERROR_PREFIX):
            return _out(
                DISPATCH_FAILED,
                detail=detail[len(DISPATCH_ERROR_PREFIX):].strip(),
                session_id=session.canopy_session_id,
            )
        return _out(NOT_DISPATCHED, session_id=session.canopy_session_id)

    turn_id = message.canopy_turn_id
    try:
        token = client.exchange_token(
            (getattr(session.owner, "email", "") or settings.CANOPY_RUN_ACTOR_FALLBACK_EMAIL),
            ttl=300,
        )["token"]
        turn = client.get_turn(token, turn_id)
    except client.CanopyError as exc:
        log.warning("canopy unreachable reading turn %s: %s", turn_id, exc)
        return _out(UNKNOWN, detail=str(exc), turn_id=turn_id,
                    session_id=session.canopy_session_id)

    state = _TURN_STATUS.get(turn.get("status", ""), UNKNOWN)
    detail = turn.get("result_note", "") or ""

    if state == QUEUED:
        # Only a QUEUED turn can be unclaimable, and only then is the extra call
        # worth making. A turn younger than canopy's 150s UNCLAIMABLE_GRACE is
        # simply absent from the list — that grace is canopy's, and we do not
        # add a second one here.
        try:
            rows = client.list_unclaimable(token)
        except client.CanopyError:
            rows = []
        row = next((r for r in rows if str(r.get("turn_id")) == turn_id), None)
        if row is not None:
            # `kind` is ADVISORY. canopy computes "could any runner ever take
            # this?" from runners the CALLING USER paired, and ace's delegated
            # user has paired none — so in practice this is always "config".
            # Both states render as "no runner available"; the distinction is a
            # hint, never a branch anything depends on.
            kind = row.get("kind", "config")
            state = WAITING_FOR_RUNNER if kind == "offline" else NO_RUNNER_CONFIGURED
            detail = row.get("reason", "") or detail

    return _out(state, detail=detail, turn_id=turn_id,
                session_id=session.canopy_session_id)
```

- [ ] **Step 4: Run the tests, confirm they pass.**

Run: `uv run pytest tests/test_canopy_run_state.py -v`
Expected: 15 passed (8 explicit + 8 parametrized cases, minus overlap).

- [ ] **Step 5: Commit.**

```bash
git add apps/canopy/run_state.py tests/test_canopy_run_state.py
git commit -m "feat(canopy): model 'no runner available' as a first-class run state

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Reconcile — write the canopy turn's outcome back onto the run

**Files:**
- Modify: `apps/canopy/run_state.py`
- Create: `apps/canopy/management/__init__.py`, `apps/canopy/management/commands/__init__.py`, `apps/canopy/management/commands/reconcile_canopy_runs.py`
- Test: `tests/test_canopy_run_state.py` (append)

**Interfaces:**
- Consumes: `run_state.execution_state`.
- Produces: `run_state.reconcile_session(session) -> dict` (the same dict `execution_state` returns, after persisting); `manage.py reconcile_canopy_runs [--workspace <slug>] [--limit N]`.

Why a reconciler exists at all: ace-web has **no** Celery, **no** signals, and **no** background worker (verified: `grep -rn "celery|@receiver|post_save"` → zero hits across the repo). Its established pattern is compute-on-read (see the `/structure` endpoint) plus a management command for the deploy hook. Follow it; do not introduce a scheduler.

What reconcile writes: the ace-web `Message.status` state machine (`pending → streaming → complete | error`) is what `Session.interrupted()` and `Session.resumable_after_deploy()` read, and what the post-deploy self-heal depends on. A canopy-executed run must keep that machine truthful.

| execution state | `Message.status` | `Session.driver_heartbeat_at` |
|---|---|---|
| `queued`, `no_runner_configured`, `waiting_for_runner` | `pending` | **stamped `now()`** — the run is genuinely alive-and-waiting; leaving the beat stale would make the deploy sweep re-resume a run that is simply waiting for a runner, forever |
| `running` | `streaming` | stamped `now()` |
| `done` | `complete` | untouched |
| `failed`, `lost`, `missed`, `cancelled` | `error`, `error_detail=f"canopy:{state}: {detail}"` | untouched |
| `unknown`, `dispatch_failed`, `not_dispatched` | untouched | untouched |

The `error_detail` prefix is `canopy:` and deliberately does **not** start with `cancelled` — `resumable_after_deploy`'s `graceful_cancel` leg matches `error_detail__startswith="cancelled"`, and a canopy-cancelled turn must not be auto-resumed by the next deploy.

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_canopy_run_state.py`:

```python
@override_settings(**ON)
def test_reconcile_marks_a_done_turn_complete():
    s = _session_with_turn()
    ex, get, unc = _canopy(turn={"status": "done", "result_note": "ok"})
    with ex, get, unc:
        run_state.reconcile_session(s)
    m = Message.objects.get(session=s, role="assistant")
    assert m.status == "complete"


@override_settings(**ON)
def test_reconcile_marks_a_failed_turn_error_without_the_cancelled_prefix():
    s = _session_with_turn()
    ex, get, unc = _canopy(turn={"status": "failed", "result_note": "boom"})
    with ex, get, unc:
        run_state.reconcile_session(s)
    m = Message.objects.get(session=s, role="assistant")
    assert m.status == "error"
    assert m.error_detail.startswith("canopy:failed")
    # Must NOT match resumable_after_deploy's graceful_cancel leg.
    assert not m.error_detail.startswith("cancelled")


@override_settings(**ON)
def test_reconcile_keeps_the_heartbeat_fresh_while_waiting_for_a_runner():
    """A run waiting on a runner is alive. A stale beat would make the
    post-deploy sweep resume it on every single deploy, forever."""
    s = _session_with_turn()
    rows = [{"turn_id": "turn-1", "kind": "config", "reason": "no runner"}]
    ex, get, unc = _canopy(turn={"status": "queued"}, unclaimable=rows)
    with ex, get, unc:
        run_state.reconcile_session(s)
    s.refresh_from_db()
    assert s.driver_heartbeat_at is not None
    assert Message.objects.get(session=s, role="assistant").status == "pending"


@override_settings(**ON)
def test_reconcile_leaves_everything_alone_when_canopy_is_unreachable():
    from apps.canopy.client import CanopyError

    s = _session_with_turn()
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(502, "down")):
        out = run_state.reconcile_session(s)
    assert out["state"] == "unknown"
    assert Message.objects.get(session=s, role="assistant").status == "pending"
```

- [ ] **Step 2: Run them, confirm they fail.**

Run: `uv run pytest tests/test_canopy_run_state.py -k reconcile -v`
Expected: FAIL — `AttributeError: module 'apps.canopy.run_state' has no attribute 'reconcile_session'`.

- [ ] **Step 3: Implement `reconcile_session`.** Append to `apps/canopy/run_state.py`:

```python
_ALIVE = (QUEUED, NO_RUNNER_CONFIGURED, WAITING_FOR_RUNNER, RUNNING)
_TERMINAL_ERROR = ("failed", "lost", "missed", "cancelled")


def reconcile_session(session) -> dict:
    """Read the run's canopy state and write it back onto ace-web's own rows.

    ace-web has no worker, no queue and no signals — the repo's pattern is
    compute-on-read plus a management command for the deploy hook. This is
    called from both.
    """
    from django.utils import timezone

    from apps.sessions.models import Message, Session

    out = execution_state(session)
    state = out["state"]
    message = _latest_assistant(session)
    if message is None or state in (UNKNOWN, DISPATCH_FAILED, NOT_DISPATCHED):
        return out

    if state in _ALIVE:
        # A run waiting on a runner is ALIVE, not abandoned. Without this beat,
        # Session.resumable_after_deploy() would match it on every deploy and
        # resume it forever — the hard_kill leg keys on a stale
        # driver_heartbeat_at with a non-terminal assistant message, which is
        # exactly the shape of a turn that is legitimately queued.
        Session.objects.filter(pk=session.pk).update(driver_heartbeat_at=timezone.now())
        want = "streaming" if state == RUNNING else "pending"
        if message.status != want:
            Message.objects.filter(pk=message.pk).update(status=want)
    elif state == "done":
        Message.objects.filter(pk=message.pk).update(
            status="complete", completed_at=timezone.now(),
        )
    elif state in _TERMINAL_ERROR:
        # `canopy:` prefix, never `cancelled…` — resumable_after_deploy's
        # graceful_cancel leg matches error_detail__startswith="cancelled", and
        # a canopy-cancelled turn must not be auto-resumed by the next deploy.
        Message.objects.filter(pk=message.pk).update(
            status="error",
            error_detail=f"canopy:{state}: {out['detail']}".strip(),
            completed_at=timezone.now(),
        )
    return out
```

- [ ] **Step 4: Add the management command.** Create `apps/canopy/management/__init__.py` and `apps/canopy/management/commands/__init__.py` (both empty), then `apps/canopy/management/commands/reconcile_canopy_runs.py`:

```python
"""Reconcile every canopy-dispatched run's state back onto its ace-web rows.

Run from the post-deploy hook alongside `resume-interrupted`, or from cron.
ace-web has no worker; this and the compute-on-read path in
`apps/sessions/api.py::session_execution` are the only two reconcilers.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Reconcile canopy-dispatched runs (turn status -> ace-web message status)."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", default="", help="Limit to one workspace slug.")
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **options):
        from apps.canopy.run_state import reconcile_session
        from apps.sessions.models import Session

        qs = Session.objects.exclude(canopy_session_id="").order_by("-updated_at")
        if options["workspace"]:
            qs = qs.filter(workspace__slug=options["workspace"])
        counts: dict[str, int] = {}
        for session in qs[: options["limit"]]:
            try:
                state = reconcile_session(session)["state"]
            except Exception as exc:  # noqa: BLE001 — one bad run must not stop the sweep
                self.stderr.write(f"{session.slug}: {exc}")
                continue
            counts[state] = counts.get(state, 0) + 1
        for state, n in sorted(counts.items()):
            self.stdout.write(f"{state}: {n}")
```

- [ ] **Step 5: Run the tests, confirm they pass.**

Run: `uv run pytest tests/test_canopy_run_state.py -v`
Expected: all green.

- [ ] **Step 6: Commit.**

```bash
git add apps/canopy/run_state.py apps/canopy/management tests/test_canopy_run_state.py
git commit -m "feat(canopy): reconcile canopy turn status back onto ace-web run rows

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Surface the state — API + the run list

**Files:**
- Modify: `apps/sessions/api.py` (new route, after `resume_run` at line 348)
- Modify: `apps/opps/api.py` (`list_opp_runs_for_workspace`, lines 816-878)
- Create: `frontend/src/canopy/runState.ts`, `frontend/src/components/opps/RunExecutionBadge.tsx`
- Modify: `frontend/src/components/views/hierarchy/OppRunsList.tsx` (`ProgressLabel`, lines 78-110)
- Test: `apps/sessions/tests/test_api.py` (append), `frontend/src/components/opps/__tests__/RunExecutionBadge.test.tsx` (create)

**Interfaces:**
- Produces: `GET /api/w/{workspace_slug}/sessions/{slug}/execution` → `{"state": str, "detail": str, "canopy_turn_id": str, "canopy_session_id": str}`; each dict from `list_opp_runs_for_workspace` gains `execution: {...} | None`; `frontend/src/canopy/runState.ts` exports `type RunExecutionState` and `describeRunExecution(state, detail) -> {label: string, tone: "muted"|"warning"|"destructive"|"foreground", hint: string}`.

- [ ] **Step 1: Write the failing backend test.** Append to `apps/sessions/tests/test_api.py`:

```python
def test_execution_endpoint_reports_the_run_state(client, ...):
    """GET /{slug}/execution surfaces the canopy-derived state; a non-member 404s."""
    from unittest import mock

    with mock.patch(
        "apps.canopy.run_state.reconcile_session",
        return_value={"state": "no_runner_configured", "detail": "no runner can take this session",
                      "canopy_turn_id": "turn-1", "canopy_session_id": "sess-1"},
    ):
        r = client.get(f"/api/w/{workspace.slug}/sessions/{session.slug}/execution")
    assert r.status_code == 200
    assert r.json()["state"] == "no_runner_configured"


def test_execution_endpoint_404s_an_unknown_session(client, ...):
    r = client.get(f"/api/w/{workspace.slug}/sessions/does-not-exist/execution")
    assert r.status_code == 404
```

Fill the `...` fixtures by copying the setup from the adjacent session-detail tests in the same file.

- [ ] **Step 2: Run it, confirm it fails.**

Run: `uv run pytest apps/sessions/tests/test_api.py -k execution -v`
Expected: FAIL — 404 on a session that exists (route not registered).

- [ ] **Step 3: Add the route.** In `apps/sessions/api.py`, after `resume_run` (line 348):

```python
@router.get("/{slug}/execution", summary="Where this run's execution actually stands")
def session_execution(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> HttpResponse:
    """The run's canopy execution state — including the two states that say, in
    plain words, that nothing can run it: `no_runner_configured` and
    `waiting_for_runner`. Reconciles on read (ace-web has no worker; this is the
    same compute-on-read shape `/structure` uses).

    The monkeypatch target in contract tests is
    `apps.canopy.run_state.reconcile_session`.
    """
    from django.http import JsonResponse

    from apps.canopy.run_state import reconcile_session

    workspace = resolve_workspace_for_member(request, workspace_slug)
    session = _load_session_in_workspace(slug, workspace)
    if session is None:
        raise ProblemError(404, "Session not found", type_=TYPE_NOT_FOUND)
    return JsonResponse(reconcile_session(session))
```

- [ ] **Step 4: Enrich the run list.** In `apps/opps/api.py::list_opp_runs_for_workspace`, inside the `for r in runs:` loop and immediately before `out.append(rich)`, add:

```python
        # Execution state (spec 2026-07-26, item 6). A run whose canopy turn no
        # runner can claim must not render as "queued" — that is exactly the
        # "looks like it is working" failure this exists to remove. None when the
        # run was never dispatched to canopy (legacy/local execution).
        rich["execution"] = _run_execution_for(workspace, slug, r.run_id)
```

and add the helper just above `list_opp_runs_for_workspace`:

```python
def _run_execution_for(workspace, slug: str, run_id: str) -> dict | None:
    """The canopy execution state for one run, or None if it never went to canopy.

    Never raises: the runs list is the opp workbench's primary read and must not
    fail because canopy is having a bad minute.
    """
    from apps.sessions.models import Session

    session = (
        Session.objects.filter(workspace=workspace, opp_slug=slug, opp_run_id=run_id)
        .exclude(canopy_session_id="")
        .order_by("-created_at")
        .first()
    )
    if session is None:
        return None
    try:
        from apps.canopy.run_state import execution_state

        return execution_state(session)
    except Exception:  # noqa: BLE001
        return None
```

Note this uses `execution_state` (read-only), **not** `reconcile_session` — a list read must not write.

- [ ] **Step 5: Write the failing frontend test.** Create `frontend/src/components/opps/__tests__/RunExecutionBadge.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunExecutionBadge } from "../RunExecutionBadge";

describe("RunExecutionBadge", () => {
  it("says no runner is available rather than 'queued'", () => {
    render(<RunExecutionBadge state="no_runner_configured" detail="no runner can take this session" />);
    expect(screen.getByText(/no runner available/i)).toBeInTheDocument();
    expect(screen.queryByText(/^queued$/i)).toBeNull();
  });

  it("distinguishes a runner that is merely offline", () => {
    render(<RunExecutionBadge state="waiting_for_runner" detail="none are reachable right now" />);
    expect(screen.getByText(/waiting for a runner/i)).toBeInTheDocument();
  });

  it("never claims a run is working when canopy could not be reached", () => {
    render(<RunExecutionBadge state="unknown" detail="502" />);
    expect(screen.getByText(/state unknown/i)).toBeInTheDocument();
  });

  it("renders nothing for a run that was never dispatched to canopy", () => {
    const { container } = render(<RunExecutionBadge state="not_dispatched" detail="" />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 6: Run it, confirm it fails.**

Run: `cd frontend && npx vitest run src/components/opps/__tests__/RunExecutionBadge.test.tsx`
Expected: FAIL — cannot resolve `../RunExecutionBadge`.

- [ ] **Step 7: Implement the frontend.** Create `frontend/src/canopy/runState.ts`:

```ts
/**
 * A run's execution state, as reported by ace-web's `/sessions/{slug}/execution`
 * and embedded on each run dict from `/opps/{slug}/runs`.
 *
 * `no_runner_configured` is the NORMAL day-one state: there is no session-capable
 * canopy cloud runner online, so a dispatched turn sits QUEUED and canopy
 * classifies it after a 150s grace. Rendering it as "queued" would make a run
 * that will never start look like one about to.
 */
export type RunExecutionState =
  | "not_dispatched"
  | "queued"
  | "no_runner_configured"
  | "waiting_for_runner"
  | "running"
  | "done"
  | "failed"
  | "cancelled"
  | "lost"
  | "missed"
  | "dispatch_failed"
  | "unknown";

export interface RunExecution {
  state: RunExecutionState;
  detail: string;
  canopy_turn_id: string;
  canopy_session_id: string;
}

export type Tone = "muted" | "warning" | "destructive" | "foreground";

export function describeRunExecution(
  state: RunExecutionState,
  detail: string,
): { label: string; tone: Tone; hint: string } | null {
  switch (state) {
    case "not_dispatched":
      return null;
    case "queued":
      return { label: "queued", tone: "muted", hint: "Enqueued; a runner has not picked it up yet." };
    case "no_runner_configured":
      return {
        label: "no runner available",
        tone: "warning",
        hint: detail || "No runner is configured to execute this run. It will not start until one is.",
      };
    case "waiting_for_runner":
      return {
        label: "waiting for a runner",
        tone: "warning",
        hint: detail || "A runner can execute this run, but none are reachable right now.",
      };
    case "running":
      return { label: "running", tone: "foreground", hint: "A runner is executing this run." };
    case "done":
      return { label: "complete", tone: "muted", hint: "" };
    case "dispatch_failed":
      return { label: "dispatch failed", tone: "destructive", hint: detail };
    case "unknown":
      return { label: "state unknown", tone: "muted", hint: detail || "canopy could not be reached." };
    default:
      return { label: state, tone: "destructive", hint: detail };
  }
}
```

Create `frontend/src/components/opps/RunExecutionBadge.tsx`:

```tsx
import { describeRunExecution, type RunExecutionState } from "../../canopy/runState";

const TONE_CLASS: Record<string, string> = {
  muted: "border-border/70 text-muted-foreground",
  foreground: "border-border text-foreground",
  warning: "border-warning/30 bg-warning/10 text-warning",
  destructive: "border-destructive/30 bg-destructive/10 text-destructive",
};

export function RunExecutionBadge({
  state,
  detail,
}: {
  state: RunExecutionState;
  detail: string;
}) {
  const described = describeRunExecution(state, detail);
  if (!described) return null;
  return (
    <span
      title={described.hint}
      className={`shrink-0 rounded border px-1.5 py-0 text-[10px] ${TONE_CLASS[described.tone]}`}
    >
      {described.label}
    </span>
  );
}
```

- [ ] **Step 8: Stop `OppRunsList` lying.** In `frontend/src/components/views/hierarchy/OppRunsList.tsx::ProgressLabel`, replace the final `"queued"` fallback branch (case 3 in its comment block, lines ~100-110) so that when `run.execution` is present and its state is not `not_dispatched`, the badge wins over the bare `"queued"` string:

```tsx
  // 3. Nothing done yet → the run's EXECUTION state if canopy knows one,
  //    otherwise "queued". A run whose turn no runner can claim used to render
  //    identically to one about to start; that is the defect this closes.
  if (run.execution && run.execution.state !== "not_dispatched") {
    return (
      <span className="min-w-0 flex-1 truncate">
        <RunExecutionBadge state={run.execution.state} detail={run.execution.detail} />
      </span>
    );
  }
  return <span className="min-w-0 flex-1 truncate text-muted-foreground">queued</span>;
```

Add `execution?: RunExecution | null;` to the `RunSummary` type in `frontend/src/api/types.ws.ts` (next to `lifecycle_status` at line 344), and import `RunExecutionBadge` + `RunExecution` at the top of `OppRunsList.tsx`.

- [ ] **Step 9: Run everything.**

Run: `uv run pytest && cd frontend && npm run test && npm run build`
Expected: all green.

- [ ] **Step 10: Regenerate types, commit, open PR B.**

```bash
cd frontend && npm run gen:api:local && cd ..
git add apps/sessions/api.py apps/opps/api.py apps/sessions/tests/test_api.py frontend/src
git commit -m "feat(canopy): surface 'no runner available' as a run state, not a silent queue

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push -u origin feat/canopy-run-state
gh pr create --title "feat(canopy): explicit no-runner-available run state" --body "$(cat <<'EOF'
Item 6 of the run-execution convergence spec.

With no session-capable cloud runner online, a dispatched turn sits QUEUED
forever and `OppRunsList` renders it as "queued" — indistinguishable from a run
about to start. This models it as a run state instead.

Note: canopy's `unclaimable` `kind` is advisory here. It computes "could any
runner ever take this?" from runners the CALLING user paired, and ace's delegated
user has paired none — so in practice it is always "config". Both states render
honestly; nothing branches on the distinction.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
gh pr merge --auto --squash
```

---

# PR C — cost + structure read canopy's retained transcript (`feat/canopy-run-transcripts`)

Branch off PR B's merge. This is Item 5.

Today, both derivations start from local bytes:
- **Cost** is computed at *write* time by `apps/ingest/live_ingest.py::store_session_transcript`, from the `raw_sink` the subprocess captured, and stored on `Session.cost_breakdown`. `GET /{slug}/cost` just reads that field back.
- **Structure** is recomputed on *every read* by `apps/sessions/api.py::get_structure_tree`, from `session.ingest_records.order_by("-created_at").first().raw_jsonl_gz`.

Once execution moves to canopy there is no `raw_sink` — the bytes live on canopy, per turn, behind `GET /api/harness/turns/{turn_id}/transcript`.

**The design:** canopy becomes the source of record for canopy-executed sessions. `IngestUpload.raw_jsonl_gz` is **demoted from source-of-record to a re-fetchable cache**, explicitly labelled (`source="canopy"`) and keyed by the turn ids it was built from (`canopy_turn_ids`). It stays the sole source-of-record for `source="local"` rows — every uploaded transcript (`POST /api/ingest/upload`) and every pre-migration row. Nothing is deleted, nothing is rewritten.

Why a cache and not pure read-through: `TRANSCRIPT_TURN_MAX_BYTES` is **100 MB** per turn on canopy, and structure recomputes on every page view. A read-through with no cache would pull up to 100 MB per turn over HTTP on every render of the structure tree. The cache key is a turn-id list, and terminal turns are immutable, so the cache is trivially invalidatable — `canopy_turn_ids` changing means refetch.

---

### Task 8: The transcript client — and the wire-format trap

**Files:**
- Create: `apps/canopy/transcripts.py`
- Modify: `config/settings/base.py`
- Test: `tests/test_canopy_transcripts.py` (create)

**Interfaces:**
- Produces: `transcripts.fetch_turn_transcript(user_token: str, turn_id: str, *, max_bytes: int | None = None) -> bytes`; `transcripts.TranscriptTooLarge(Exception)`; `transcripts.TranscriptEncodingError(Exception)`.
- Adds `settings.CANOPY_TRANSCRIPT_MAX_BYTES` (default `64 * 1024 * 1024`).

**Read this before writing a line of it.** canopy's `GET /api/harness/turns/{turn_id}/transcript` is a `StreamingHttpResponse` of **incrementally-inflated plaintext**, `Content-Type: application/x-ndjson`. An earlier canopy attempt served the still-gzipped bytes with `Content-Encoding: gzip`, and a follow-up review empirically falsified the assumption that clients would inflate it: canopy stores the blob as **concatenated multi-member gzip** (`append_transcript` compresses each batch and concatenates the members), and both `curl --compressed` and `httpx` return only the **first member** — a 200 with silently truncated content and no error. canopy fixed it by streaming plaintext. This client must not re-introduce the gamble from the other end:

1. Use `urllib.request` (which sends no `Accept-Encoding` and performs no content-decoding), matching the rest of `apps/canopy/client.py`. **Do not use `httpx` here.**
2. **Assert the response is not content-encoded** and raise if it is. If a proxy or a future middleware re-introduces `Content-Encoding: gzip`, this must fail loudly rather than hand a truncated transcript to the cost aggregator — a silently short transcript produces a silently wrong cost number, which is worse than an error.
3. Read in bounded chunks with a hard byte ceiling. An empty 200 is normal (a turn with nothing appended reads as empty, not 404).
4. Tolerate canopy's synthetic truncation marker: when a turn crosses `TRANSCRIPT_TURN_MAX_BYTES`, canopy writes one line `{"type": "canopy_transcript_truncated", "reason": "..."}`. `parse_session_bytes` will encounter an unknown `type` — verify it skips it rather than raising (`apps/ingest/parser.py:92-96` switches on `type` and falls through), and add a test that proves it.

- [ ] **Step 1: Settings.** In `config/settings/base.py`, below `CANOPY_RUN_ACTOR_FALLBACK_EMAIL`:

```python
# Ceiling on a single turn transcript fetched from canopy. canopy's own per-turn
# cap is 100 MB; this is ace-web's defensive limit on what it will pull into a
# web worker's memory to re-derive cost/structure from.
CANOPY_TRANSCRIPT_MAX_BYTES = env.int("CANOPY_TRANSCRIPT_MAX_BYTES", default=64 * 1024 * 1024)
```

- [ ] **Step 2: Write the failing tests.** Create `tests/test_canopy_transcripts.py`:

```python
"""apps.canopy.transcripts — pulling a turn's raw JSONL back from canopy."""

import io
from unittest import mock

import pytest
from django.test import override_settings

from apps.canopy import transcripts

ENABLED = dict(CANOPY_BASE_URL="http://canopy.test", CANOPY_APP_CREDENTIAL="c")


class _Stream(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


def _urlopen(data, headers=None):
    return mock.patch(
        "apps.canopy.transcripts.urllib.request.urlopen",
        return_value=_Stream(data, headers),
    )


@override_settings(**ENABLED)
def test_fetches_plaintext_ndjson_verbatim():
    body = b'{"type":"system"}\n{"type":"assistant"}\n'
    with _urlopen(body) as opened:
        out = transcripts.fetch_turn_transcript("tok", "turn-1")
    assert out == body
    req = opened.call_args.args[0]
    assert req.full_url == "http://canopy.test/api/harness/turns/turn-1/transcript"
    # urllib sends no Accept-Encoding of its own; we must not add one either.
    assert req.get_header("Accept-encoding") is None


@override_settings(**ENABLED)
def test_a_turn_with_no_transcript_reads_as_empty_not_an_error():
    with _urlopen(b""):
        assert transcripts.fetch_turn_transcript("tok", "turn-1") == b""


@override_settings(**ENABLED)
def test_a_content_encoded_response_is_refused_loudly():
    """canopy streams PLAINTEXT. If anything re-introduces Content-Encoding:
    gzip, urllib hands us raw bytes and, because the blob is multi-member gzip,
    a naive inflate would silently return only the FIRST member — a truncated
    transcript, a wrong cost number, and no error anywhere. Fail instead."""
    with _urlopen(b"\x1f\x8b garbage", headers={"Content-Encoding": "gzip"}):
        with pytest.raises(transcripts.TranscriptEncodingError):
            transcripts.fetch_turn_transcript("tok", "turn-1")


@override_settings(**ENABLED, CANOPY_TRANSCRIPT_MAX_BYTES=16)
def test_a_transcript_over_the_ceiling_raises_rather_than_truncating():
    with _urlopen(b"x" * 64):
        with pytest.raises(transcripts.TranscriptTooLarge):
            transcripts.fetch_turn_transcript("tok", "turn-1")


def test_canopys_truncation_marker_line_survives_the_parser():
    """canopy writes one synthetic line when a turn crosses its 100MB cap. The
    aggregators must skip it, not crash on it."""
    from apps.ingest.parser import parse_session_bytes

    raw = (
        b'{"type":"assistant","uuid":"u1","message":{"model":"m","usage":{"input_tokens":1},'
        b'"content":[{"type":"text","text":"hi"}]}}\n'
        b'{"type":"canopy_transcript_truncated","reason":"exceeded"}\n'
    )
    parsed, events = parse_session_bytes(raw)
    assert parsed.line_count == 2
    assert len(events) >= 1
```

- [ ] **Step 3: Run them, confirm they fail.**

Run: `uv run pytest tests/test_canopy_transcripts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.canopy.transcripts'`.

- [ ] **Step 4: Implement.** Create `apps/canopy/transcripts.py`:

```python
"""Read a turn's retained raw JSONL back from canopy.

canopy's `GET /api/harness/turns/{id}/transcript` is a StreamingHttpResponse of
INCREMENTALLY-INFLATED PLAINTEXT (`application/x-ndjson`). That wire format is
load-bearing and was arrived at the hard way: canopy stores the blob as
CONCATENATED MULTI-MEMBER gzip, and an earlier attempt to serve it with
`Content-Encoding: gzip` was empirically falsified — both `curl --compressed`
and `httpx` return only the FIRST member, i.e. a 200 with silently truncated
content and no error.

So: `urllib.request` (no Accept-Encoding, no content-decoding, matching
apps/canopy/client.py), a hard refusal if anything ever content-encodes the
response, and a byte ceiling. A short transcript produces a wrong cost number
with no symptom, which is strictly worse than an exception.
"""

from __future__ import annotations

import urllib.error
import urllib.request

from django.conf import settings

from .client import CanopyError

_CHUNK = 256 * 1024


class TranscriptTooLarge(Exception):
    pass


class TranscriptEncodingError(Exception):
    pass


def fetch_turn_transcript(user_token: str, turn_id: str, *, max_bytes: int | None = None) -> bytes:
    """The turn's raw JSONL, byte for byte. Empty bytes when nothing was ever
    appended — absence of a transcript is not absence of a turn."""
    ceiling = max_bytes or settings.CANOPY_TRANSCRIPT_MAX_BYTES
    req = urllib.request.Request(
        f"{settings.CANOPY_BASE_URL}/api/harness/turns/{turn_id}/transcript",
        headers={"Authorization": f"Bearer {user_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            encoding = (resp.getheader("Content-Encoding") or "").strip().lower()
            if encoding and encoding != "identity":
                raise TranscriptEncodingError(
                    f"canopy transcript came back Content-Encoding: {encoding!r}; "
                    "this route must stream plaintext (a multi-member gzip body "
                    "silently truncates to its first member)"
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > ceiling:
                    raise TranscriptTooLarge(
                        f"turn {turn_id} transcript exceeds {ceiling} bytes"
                    )
                chunks.append(chunk)
            return b"".join(chunks)
    except urllib.error.HTTPError as exc:
        raise CanopyError(exc.code, exc.read().decode(errors="replace")[:300]) from exc
    except urllib.error.URLError as exc:
        raise CanopyError(502, str(exc.reason)) from exc
```

- [ ] **Step 5: Run the tests, confirm they pass.**

Run: `uv run pytest tests/test_canopy_transcripts.py -v`
Expected: 5 passed. If the truncation-marker test fails, fix `apps/ingest/parser.py` to skip unknown `type` values rather than raise — and keep that test.

- [ ] **Step 6: Commit.**

```bash
git add apps/canopy/transcripts.py config/settings/base.py tests/test_canopy_transcripts.py
git commit -m "feat(canopy): fetch a turn's retained transcript, refusing any content-encoding

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: The transcript source seam + the `IngestUpload` migration

**Files:**
- Modify: `apps/sessions/models.py` (`IngestUpload`)
- Create: `apps/sessions/migrations/0011_ingestupload_source.py`
- Create: `apps/ingest/sources.py`
- Test: `apps/ingest/tests/test_sources.py` (create)

**Interfaces:**
- Produces: `IngestUpload.source: str` (`"local"` | `"canopy"`, default `"local"`), `IngestUpload.canopy_turn_ids: list` (JSONField, default `list`); `sources.session_raw_jsonl(session) -> bytes | None`; `sources.refresh_canopy_cache(session) -> IngestUpload | None`.

**The migration for existing rows.** Every existing `IngestUpload` was produced either by `POST /api/ingest/upload` or by the local turn driver — both are `"local"`. The migration adds the two fields with defaults, and that is the entire backfill: `source` defaults to `"local"`, so every pre-existing row is correctly labelled with zero data movement. **Nothing existing is rewritten or deleted.** A `"local"` row stays the source of record forever; only sessions that carry `canopy_session_id` ever get a `"canopy"` row.

- [ ] **Step 1: Write the failing tests.** Create `apps/ingest/tests/test_sources.py`:

```python
"""apps.ingest.sources — where a session's raw JSONL comes from."""

import gzip
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.ingest import sources
from apps.sessions.models import IngestUpload, Message, Session

User = get_user_model()
pytestmark = pytest.mark.django_db

ON = dict(
    CANOPY_BASE_URL="http://canopy.test", CANOPY_APP_CREDENTIAL="c",
    CANOPY_WORKSPACE="connect", CANOPY_AGENT_SLUG="ace", CANOPY_RUN_EXECUTION=True,
)

LINE_A = b'{"type":"assistant","uuid":"a"}\n'
LINE_B = b'{"type":"assistant","uuid":"b"}\n'


def _session(canopy_session_id=""):
    user = User.objects.create_user(email="o@dimagi.com")
    return user, Session.create_with_owner(
        owner=user, title="t", opp_slug="o", opp_run_id="r",
        canopy_session_id=canopy_session_id,
    )


def test_a_local_upload_is_still_read_from_the_local_blob():
    user, s = _session()
    IngestUpload.objects.create(
        session=s, uploaded_by=user, raw_jsonl_gz=gzip.compress(LINE_A), line_count=1,
    )
    assert sources.session_raw_jsonl(s) == LINE_A


def test_a_row_with_no_source_defaults_to_local():
    user, s = _session()
    row = IngestUpload.objects.create(session=s, uploaded_by=user, raw_jsonl_gz=gzip.compress(LINE_A))
    assert row.source == "local"


@override_settings(**ON)
def test_a_canopy_session_concatenates_its_turns_transcripts_in_turn_order():
    user, s = _session(canopy_session_id="sess-1")
    for idx, turn in ((1, "turn-a"), (3, "turn-b")):
        Message.objects.create(
            session=s, turn_index=idx, role="assistant", content={"text": ""},
            status="complete", canopy_turn_id=turn,
        )
    fetched = {"turn-a": LINE_A, "turn-b": LINE_B}
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch(
             "apps.canopy.transcripts.fetch_turn_transcript",
             side_effect=lambda tok, tid, **kw: fetched[tid],
         ):
        out = sources.session_raw_jsonl(s)
    assert out == LINE_A + LINE_B


@override_settings(**ON)
def test_the_canopy_fetch_is_cached_and_not_refetched():
    user, s = _session(canopy_session_id="sess-1")
    Message.objects.create(
        session=s, turn_index=1, role="assistant", content={"text": ""},
        status="complete", canopy_turn_id="turn-a",
    )
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch("apps.canopy.transcripts.fetch_turn_transcript", return_value=LINE_A) as fetch:
        sources.session_raw_jsonl(s)
        sources.session_raw_jsonl(s)
    assert fetch.call_count == 1
    row = IngestUpload.objects.get(session=s)
    assert row.source == "canopy"
    assert row.canopy_turn_ids == ["turn-a"]


@override_settings(**ON)
def test_a_new_turn_invalidates_the_cache_and_refetches():
    user, s = _session(canopy_session_id="sess-1")
    Message.objects.create(
        session=s, turn_index=1, role="assistant", content={"text": ""},
        status="complete", canopy_turn_id="turn-a",
    )
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch("apps.canopy.transcripts.fetch_turn_transcript", return_value=LINE_A):
        sources.session_raw_jsonl(s)
    Message.objects.create(
        session=s, turn_index=3, role="assistant", content={"text": ""},
        status="complete", canopy_turn_id="turn-b",
    )
    fetched = {"turn-a": LINE_A, "turn-b": LINE_B}
    with mock.patch("apps.canopy.client.exchange_token", return_value={"token": "t"}), \
         mock.patch(
             "apps.canopy.transcripts.fetch_turn_transcript",
             side_effect=lambda tok, tid, **kw: fetched[tid],
         ):
        assert sources.session_raw_jsonl(s) == LINE_A + LINE_B
    assert IngestUpload.objects.get(session=s).canopy_turn_ids == ["turn-a", "turn-b"]


@override_settings(**ON)
def test_a_canopy_failure_falls_back_to_the_cached_bytes_and_never_raises():
    from apps.canopy.client import CanopyError

    user, s = _session(canopy_session_id="sess-1")
    Message.objects.create(
        session=s, turn_index=1, role="assistant", content={"text": ""},
        status="complete", canopy_turn_id="turn-a",
    )
    IngestUpload.objects.create(
        session=s, uploaded_by=user, source="canopy", canopy_turn_ids=["turn-a"],
        raw_jsonl_gz=gzip.compress(LINE_A),
    )
    Message.objects.create(
        session=s, turn_index=3, role="assistant", content={"text": ""},
        status="complete", canopy_turn_id="turn-b",
    )
    with mock.patch("apps.canopy.client.exchange_token", side_effect=CanopyError(502, "down")):
        assert sources.session_raw_jsonl(s) == LINE_A   # stale, but never an exception
```

- [ ] **Step 2: Run them, confirm they fail.**

Run: `uv run pytest apps/ingest/tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.ingest.sources'`.

- [ ] **Step 3: Add the fields.** In `apps/sessions/models.py`, in `IngestUpload` after `raw_jsonl_gz` (line 330):

```python
    # Where these bytes came from (spec 2026-07-26, item 5).
    #   "local"  — SOURCE OF RECORD. An uploaded transcript (POST /api/ingest/
    #              upload) or a pre-canopy live capture. Never refetched.
    #   "canopy" — a CACHE of canopy's per-turn retained transcripts, keyed by
    #              `canopy_turn_ids`. canopy is the source of record; this row
    #              exists so /structure does not pull up to 100 MB per turn over
    #              HTTP on every page view. Safe to delete; it rebuilds.
    SOURCE_LOCAL, SOURCE_CANOPY = "local", "canopy"
    SOURCE_CHOICES = [(SOURCE_LOCAL, "Local"), (SOURCE_CANOPY, "Canopy")]
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_LOCAL)
    # The canopy Turn ids this cache was built from, in turn order. Cache key:
    # a differing list means refetch. Always empty for source="local".
    canopy_turn_ids = models.JSONField(default=list, blank=True)
```

- [ ] **Step 4: Generate the migration.**

Run: `uv run python manage.py makemigrations ace_sessions --name ingestupload_source`
Expected: `apps/sessions/migrations/0011_ingestupload_source.py` with two `AddField` operations. Confirm it contains no `RemoveField`, no `AlterField` on `raw_jsonl_gz`, and no `RunPython` — the `source="local"` default *is* the backfill.

- [ ] **Step 5: Implement the seam.** Create `apps/ingest/sources.py`:

```python
"""Where a session's raw JSONL comes from.

Before the run-execution convergence there was one answer: the local
`IngestUpload.raw_jsonl_gz` blob. Now there are two, and which one applies is a
property of the SESSION, not of the reader:

  * `source="local"`  — an uploaded transcript, or a pre-canopy live capture.
    Source of record. Never refetched, never rewritten.
  * `source="canopy"` — a cache of canopy's per-turn retained transcripts,
    concatenated in turn order and keyed by the turn ids it was built from.
    canopy is the source of record; deleting this row is safe.

Every read goes through `session_raw_jsonl`. Nothing else may touch
`raw_jsonl_gz` directly.
"""

from __future__ import annotations

import gzip
import hashlib
import logging

log = logging.getLogger(__name__)


def _canopy_turn_ids(session) -> list[str]:
    from apps.sessions.models import Message

    return [
        t
        for t in Message.objects.filter(session=session, role="assistant")
        .exclude(canopy_turn_id="")
        .order_by("turn_index")
        .values_list("canopy_turn_id", flat=True)
    ]


def _cached_row(session):
    from apps.sessions.models import IngestUpload

    return IngestUpload.objects.filter(session=session).order_by("-created_at").first()


def refresh_canopy_cache(session):
    """Pull every turn's transcript from canopy and re-seat the cache row.

    Returns the IngestUpload, or None when there is nothing to fetch. Raises
    nothing: a canopy outage must degrade to stale bytes, never to a 500 on the
    structure view.
    """
    from apps.canopy import client, transcripts
    from apps.sessions.models import IngestUpload

    turn_ids = _canopy_turn_ids(session)
    if not turn_ids:
        return None
    try:
        email = (getattr(session.owner, "email", "") or "").strip()
        token = client.exchange_token(email, ttl=300)["token"]
        blobs = [transcripts.fetch_turn_transcript(token, tid) for tid in turn_ids]
    except Exception:  # noqa: BLE001 — never let a canopy blip break a read
        log.warning("canopy transcript fetch failed for session %s", session.slug, exc_info=True)
        return None

    raw = b"".join(blobs)
    row, _created = IngestUpload.objects.update_or_create(
        session=session,
        defaults={
            "uploaded_by": session.owner,
            "source": IngestUpload.SOURCE_CANOPY,
            "canopy_turn_ids": turn_ids,
            "source_path": f"<canopy:{session.canopy_session_id}>",
            "raw_bytes": len(raw),
            "line_count": raw.count(b"\n"),
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_jsonl_gz": gzip.compress(raw),
            "workspace": session.workspace,
        },
    )
    return row


def session_raw_jsonl(session) -> bytes | None:
    """The session's full raw JSONL, or None if there is none to be had.

    THE single read path for transcript bytes. `apps/sessions/api.py::
    get_structure_tree` and `apps/ingest/live_ingest.py` both go through it.
    """
    from apps.sessions.models import IngestUpload

    row = _cached_row(session)
    if not session.canopy_session_id:
        # Local source of record — an uploaded transcript or a pre-canopy run.
        if row is None or not row.raw_jsonl_gz:
            return None
        return gzip.decompress(bytes(row.raw_jsonl_gz))

    wanted = _canopy_turn_ids(session)
    stale = (
        row is None
        or row.source != IngestUpload.SOURCE_CANOPY
        or list(row.canopy_turn_ids or []) != wanted
    )
    if stale and wanted:
        refreshed = refresh_canopy_cache(session)
        if refreshed is not None:
            row = refreshed
    if row is None or not row.raw_jsonl_gz:
        return None
    return gzip.decompress(bytes(row.raw_jsonl_gz))
```

- [ ] **Step 6: Run the tests, confirm they pass.**

Run: `uv run pytest apps/ingest/tests/test_sources.py -v`
Expected: 6 passed.

- [ ] **Step 7: Commit.**

```bash
git add apps/sessions/models.py apps/sessions/migrations/0011_ingestupload_source.py apps/ingest/sources.py apps/ingest/tests/test_sources.py
git commit -m "feat(ingest): resolve transcript bytes from canopy or the local blob

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Point cost and structure at the seam

**Files:**
- Modify: `apps/sessions/api.py::get_structure_tree` (lines 636-694)
- Modify: `apps/ingest/live_ingest.py::store_session_transcript`
- Modify: `apps/canopy/run_state.py::reconcile_session`
- Test: `apps/ingest/tests/test_live_ingest.py` (append), `apps/sessions/tests/test_api.py` (append)

**Interfaces:**
- Consumes: `sources.session_raw_jsonl`.
- Produces: `live_ingest.recompute_cost_from_source(session) -> dict` — recompute `Session.cost_breakdown` from whatever `session_raw_jsonl` returns, without touching `raw_jsonl_gz`.

Cost is precomputed and stored (`Session.cost_breakdown`); nothing recomputes it on read. With canopy executing, the moment to recompute is when `reconcile_session` first observes a terminal turn.

- [ ] **Step 1: Write the failing tests.** Append to `apps/ingest/tests/test_live_ingest.py`:

```python
@override_settings(**ON)
def test_recompute_cost_from_source_uses_the_canopy_transcript():
    user, s = _canopy_session_with_turn()   # mirror the helper in test_sources.py
    raw = (
        b'{"type":"assistant","uuid":"u1","message":{"model":"claude-opus-4-20250514",'
        b'"usage":{"input_tokens":10,"output_tokens":5},'
        b'"content":[{"type":"text","text":"hi"}]}}\n'
    )
    with mock.patch("apps.ingest.sources.session_raw_jsonl", return_value=raw):
        breakdown = live_ingest.recompute_cost_from_source(s)
    s.refresh_from_db()
    assert s.cost_breakdown == breakdown
    assert breakdown["totals"]["input_tokens"] == 10


def test_recompute_cost_is_a_noop_when_there_is_no_transcript():
    user, s = _local_session()
    with mock.patch("apps.ingest.sources.session_raw_jsonl", return_value=None):
        assert live_ingest.recompute_cost_from_source(s) == {}
```

And append to `apps/sessions/tests/test_api.py`:

```python
def test_structure_reads_through_the_transcript_source(client, ...):
    """/structure must not touch raw_jsonl_gz directly — a canopy-executed
    session has no local blob until the cache is seated."""
    from unittest import mock

    raw = b'{"type":"assistant","uuid":"u1","message":{"content":[{"type":"text","text":"x"}]}}\n'
    with mock.patch("apps.ingest.sources.session_raw_jsonl", return_value=raw) as src:
        r = client.get(f"/api/w/{workspace.slug}/sessions/{session.slug}/structure")
    assert r.status_code == 200
    src.assert_called_once()


def test_structure_reports_no_raw_jsonl_when_the_source_has_nothing(client, ...):
    from unittest import mock

    with mock.patch("apps.ingest.sources.session_raw_jsonl", return_value=None):
        r = client.get(f"/api/w/{workspace.slug}/sessions/{session.slug}/structure")
    assert r.json()["unavailable_reason"] == "no-raw-jsonl"
```

- [ ] **Step 2: Run them, confirm they fail.**

Run: `uv run pytest apps/ingest/tests/test_live_ingest.py apps/sessions/tests/test_api.py -k "recompute or structure" -v`
Expected: FAIL — `AttributeError: module 'apps.ingest.live_ingest' has no attribute 'recompute_cost_from_source'`; and the structure tests fail because `src.assert_called_once()` never fires.

- [ ] **Step 3: Rewire `get_structure_tree`.** In `apps/sessions/api.py`, replace lines 660-681 (from `upload = session.ingest_records...` through the `except` block) with:

```python
    from apps.ingest.sources import session_raw_jsonl

    raw = session_raw_jsonl(session)
    if not raw:
        return ({"schema_version": 0, "session": None, "phases": [],
                 "unavailable_reason": "no-raw-jsonl"}, None, False)

    # The ETag still comes off the cache row's content hash — for a canopy
    # session that hash is over the concatenated turn transcripts, and
    # `session_raw_jsonl` has just re-seated the row if the turn set moved, so
    # it is current by construction. Absent (pre-0006 rows) means no caching,
    # exactly as before.
    upload = session.ingest_records.order_by("-created_at").first()
    etag = (
        f'"v{SCHEMA_VERSION}:{upload.content_sha256}"'
        if upload is not None and upload.content_sha256
        else None
    )
    if etag and if_none_match == etag:
        return {}, etag, True

    try:
        _parsed, events = parse_session_bytes(raw)
        tree = aggregate(events)
    except Exception:
        _log.exception("structure aggregation failed for session %s", slug)
        return ({"schema_version": 0, "session": None, "phases": [],
                 "unavailable_reason": "parse-failed"}, None, False)

    return tree, etag, False
```

Delete the now-unused `import gzip as _gzip` at line 648 if nothing else in the module uses it.

- [ ] **Step 4: Add `recompute_cost_from_source`.** Append to `apps/ingest/live_ingest.py`:

```python
def recompute_cost_from_source(session) -> dict:
    """Recompute `Session.cost_breakdown` from whatever the transcript source
    currently yields.

    The canopy-era counterpart to `store_session_transcript`. That function
    exists because the local turn driver held the bytes and had to persist them;
    this one runs when a canopy turn goes terminal, reads the bytes back from
    canopy (via `sources.session_raw_jsonl`, which seats the cache), and writes
    only the derived breakdown. It never touches `raw_jsonl_gz` — the cache is
    `sources`' business, not this module's.
    """
    from apps.ingest.cost_aggregator import aggregate
    from apps.ingest.parser import parse_session_bytes
    from apps.ingest.sources import session_raw_jsonl

    raw = session_raw_jsonl(session)
    if not raw:
        return {}
    _parsed, cost_events = parse_session_bytes(raw)
    try:
        breakdown = aggregate(cost_events)
    except Exception:  # noqa: BLE001 — analytics must never break a run
        log.exception("cost aggregator failed for canopy session %s", session.slug)
        return {}
    session.cost_breakdown = breakdown
    session.save(update_fields=["cost_breakdown", "updated_at"])
    return breakdown
```

- [ ] **Step 5: Trigger it on terminal reconcile.** In `apps/canopy/run_state.py::reconcile_session`, inside the `elif state == "done":` branch and the `elif state in _TERMINAL_ERROR:` branch, after each `Message.objects.filter(...).update(...)`, add:

```python
        # The turn is terminal, so its transcript is final: derive cost now
        # rather than on every read (cost has always been precomputed; see
        # `get_cost_breakdown`, which only reads the stored field back).
        try:
            from apps.ingest.live_ingest import recompute_cost_from_source

            recompute_cost_from_source(session)
        except Exception:  # noqa: BLE001
            log.warning("cost recompute failed for session %s", session.slug, exc_info=True)
```

- [ ] **Step 6: Run the full suite.**

Run: `uv run pytest`
Expected: all green, including the existing `apps/ingest/tests/test_live_ingest.py` and `apps/sessions/tests/test_api.py` structure tests — a `source="local"` session's bytes still come from its own blob, so they are unaffected.

- [ ] **Step 7: Commit and open PR C.**

```bash
git add apps/sessions/api.py apps/ingest/live_ingest.py apps/canopy/run_state.py apps/ingest/tests/test_live_ingest.py apps/sessions/tests/test_api.py
git commit -m "feat(ingest): derive cost + structure from canopy's retained transcript

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push -u origin feat/canopy-run-transcripts
gh pr create --title "feat(ingest): cost + structure read canopy's retained transcript" --body "$(cat <<'EOF'
Item 5 of the run-execution convergence spec.

`IngestUpload.raw_jsonl_gz` is demoted from source-of-record to a re-fetchable,
explicitly-labelled cache for canopy-executed sessions (`source="canopy"`,
keyed by `canopy_turn_ids`). It stays the source of record for every uploaded
transcript and every pre-migration row (`source="local"`, the default — which
is the whole backfill; nothing is rewritten or deleted).

The transcript client uses `urllib.request` and REFUSES any content-encoded
response. canopy stores multi-member gzip; `curl --compressed` and `httpx` both
silently truncate that to its first member, which would produce a wrong cost
number with no symptom.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
gh pr merge --auto --squash
```

---

# PR D — the Slack path, told straight (`fix/slack-run-honesty`)

Branch off PR C's merge. Independent of the migration; it lands last because the dispatch seam it uses only exists after PR A.

---

### Task 11: Make `/ace run` do what it says

**Files:**
- Modify: `apps/slack/run_starter.py`
- Modify: `CLAUDE.md` (line ~275)
- Modify: `docs/superpowers/specs/2026-05-15-slack-integration-design.md` (lines 94-96)
- Test: `apps/slack/tests/test_run_starter.py` (create — there is no such file today)

**Interfaces:**
- Consumes: `run_dispatch.start_turn`, `apps/opps/drive_client.py::get_drive_client`.
- Produces: `start_run_from_slack` unchanged in signature (`(*, slug_or_link, user, workspace) -> tuple[str, str]`), but now creating an assistant placeholder and dispatching it.

Three defects, all pre-existing and all provable:

1. **No assistant placeholder, no dispatch.** `run_starter.py:136-144` writes one `role="user"`, `status="complete"` Message. Nothing reads it. The post-deploy sweep cannot see it (`resumable_after_deploy`/`interrupted` both require an **assistant** row). The working shape is `apps/opps/api.py:1824-1856` + `:1912`.
2. **A false docstring.** `run_starter.py:14` claims "the turn_driver picks this up and spawns the CLI". It never did — `git log --follow` shows the birth commit already ended at `return slug, run_id`. `CLAUDE.md:275` repeats the claim; `docs/superpowers/specs/2026-05-15-slack-integration-design.md:94-96` is where it originated.
3. **A guaranteed crash on the `/ace new` + PDD-link branch.** `run_starter.py:93` constructs `GoogleDriveClient(settings.ACE_DRIVE_SA_KEY_JSON)` — a raw JSON **string** where a credentials **object** is required. It is the only hand-constructed `GoogleDriveClient` in the repo.

- [ ] **Step 1: Write the failing tests.** Create `apps/slack/tests/test_run_starter.py`:

```python
"""apps.slack.run_starter — Slack-triggered runs actually execute (they never did).

Every existing Slack test mocks `start_run_from_slack` out of existence, which is
why this was green in CI since May while doing nothing.
"""

from unittest import mock

import pytest
from django.contrib.auth import get_user_model

from apps.opps.models import OppWorkspace
from apps.sessions.models import Message, Session
from apps.slack import run_starter
from apps.workspaces.models import Workspace

User = get_user_model()
pytestmark = pytest.mark.django_db


def _fixture():
    user = User.objects.create_user(email="slacker@dimagi.com")
    ws = Workspace.objects.create(
        slug="ws", display_name="ws", drive_root_folder_id="f", created_by=user,
    )
    OppWorkspace.objects.create(slug="opp-a", display_name="A", created_by=user, workspace=ws)
    return user, ws


def test_creates_an_assistant_placeholder_and_dispatches_it():
    user, ws = _fixture()
    with mock.patch("apps.canopy.run_dispatch.start_turn") as start:
        slug, run_id = run_starter.start_run_from_slack(
            slug_or_link="opp-a", user=user, workspace=ws,
        )
    assert slug == "opp-a"
    session = Session.objects.get(opp_slug="opp-a", opp_run_id=run_id)
    assistant = Message.objects.get(session=session, role="assistant")
    assert assistant.status == "pending"
    start.assert_called_once_with(assistant.id)


def test_the_created_run_is_visible_to_the_post_deploy_resume_sweep():
    """The old shape (user message only) was invisible to resumable_after_deploy
    and interrupted() forever, because both require an assistant row."""
    user, ws = _fixture()
    with mock.patch("apps.canopy.run_dispatch.start_turn"):
        run_starter.start_run_from_slack(slug_or_link="opp-a", user=user, workspace=ws)
    assert Session.interrupted(grace_seconds=0).filter(opp_slug="opp-a").exists()


def test_the_pdd_branch_uses_the_service_account_registry_not_a_raw_json_string():
    """GoogleDriveClient(settings.ACE_DRIVE_SA_KEY_JSON) passes a str where
    googleapiclient wants a credentials object -> AttributeError, swallowed by
    the caller's bare except. Empirically reproduced."""
    user, ws = _fixture()
    with mock.patch("apps.opps.drive_client.get_drive_client") as get_drive, \
         mock.patch("apps.opps.opp_creator.create_opp", return_value=("new-opp", "run-001")), \
         mock.patch("apps.canopy.run_dispatch.start_turn"):
        run_starter.start_run_from_slack(
            slug_or_link="idea: a new thing", user=user, workspace=ws,
        )
    get_drive.assert_called_once()
```

- [ ] **Step 2: Run them, confirm they fail.**

Run: `uv run pytest apps/slack/tests/test_run_starter.py -v`
Expected: FAIL — `Message.DoesNotExist` for the assistant row on the first two; `AssertionError: Expected 'get_drive_client' to have been called once` on the third.

- [ ] **Step 3: Fix the docstring.** In `apps/slack/run_starter.py`, replace the line 14 claim with:

```python
    Creates the Session, a completed user turn, and a pending assistant turn,
    then dispatches it through `apps.canopy.run_dispatch.start_turn` — the same
    seam `apps.opps.api::seeded_run` uses. Until 2026-07-26 this function
    created only the user turn and dispatched nothing, so Slack-triggered runs
    posted a "kicking off" card and then did nothing at all, forever. The old
    docstring's claim that "the turn_driver picks this up" was never true; see
    docs/plans/2026-07-26-run-convergence-ace-side.md.
```

- [ ] **Step 4: Create the assistant turn and dispatch.** In `apps/slack/run_starter.py`, after the `Message.objects.create(...)` at lines 136-144, add:

```python
        assistant = Message.objects.create(
            session=session,
            turn_index=_next_turn_index(session),
            role="assistant",
            content={"text": ""},
            plaintext="",
            status="pending",
        )
    from apps.canopy.run_dispatch import start_turn

    start_turn(assistant.id)
```

- [ ] **Step 5: Fix the Drive client.** Replace `run_starter.py:93`:

```python
    drive = GoogleDriveClient(settings.ACE_DRIVE_SA_KEY_JSON)
```

with:

```python
    from apps.opps.drive_client import get_drive_client

    # NOT GoogleDriveClient(settings.ACE_DRIVE_SA_KEY_JSON): that passes a raw
    # JSON string where googleapiclient wants a credentials object, which raises
    # AttributeError: 'str' object has no attribute 'authorize' — swallowed by
    # the caller's bare except and reported as "Internal error starting run".
    # Every other caller in the repo goes through the service-account registry.
    drive = get_drive_client(workspace=workspace)
```

Remove the now-unused `GoogleDriveClient` import if nothing else in the module uses it.

- [ ] **Step 6: Fix the two stale docs.** In `CLAUDE.md`, in the chat-retirement bullet that lists what depends on `turn_driver`, replace "Slack-triggered runs" with:

```
  Slack-triggered runs (which, until 2026-07-26, depended on the *models* only —
  `apps/slack/run_starter.py` never called the driver at all; see
  `docs/plans/2026-07-26-run-convergence-ace-side.md`)
```

In `docs/superpowers/specs/2026-05-15-slack-integration-design.md`, replace the `→ existing turn_driver spawns claude -p …` line in the diagram at lines 94-96 with `→ creates a pending assistant turn → run_dispatch.start_turn`, and add a one-line note that the original claim was an assumption never implemented.

- [ ] **Step 7: Run the tests, confirm they pass.**

Run: `uv run pytest apps/slack/ -v`
Expected: all green, including the four pre-existing tests that mock `start_run_from_slack` — they patch the whole function, so its internals changing does not affect them.

- [ ] **Step 8: Commit and open PR D.**

```bash
git add apps/slack/run_starter.py apps/slack/tests/test_run_starter.py CLAUDE.md docs/superpowers/specs/2026-05-15-slack-integration-design.md
git commit -m "fix(slack): Slack-triggered runs actually execute, and the docs stop lying

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push -u origin fix/slack-run-honesty
gh pr create --title "fix(slack): /ace run has never executed anything — wire it up" --body "$(cat <<'EOF'
`apps/slack/run_starter.py` created a Session and a single completed USER
Message and returned. No assistant placeholder, no driver call, no signal, no
worker — and the post-deploy resume sweep could never see it, because
`resumable_after_deploy`/`interrupted` both require an assistant row. `/ace run`
posted "🚀 Kicking off…" and did nothing, forever.

`git log --follow` shows the wiring was never present: the birth commit already
ended at `return slug, run_id`. The claim came from a design doc and was
transcribed into the module docstring. Every test mocked
`start_run_from_slack`, so CI stayed green.

Separately, `/ace new` and `/ace run <pdd-link>` crash before creating anything:
`GoogleDriveClient(settings.ACE_DRIVE_SA_KEY_JSON)` passes a str where a
credentials object is required.

This wires both branches through `run_dispatch.start_turn`, fixes the Drive
client, adds the first tests this module has ever had, and corrects the two
stale docs.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
gh pr merge --auto --squash
```

---

### Task 12: Retire `turn_driver` — **DO NOT EXECUTE YET**

**Files (when it eventually runs):**
- Delete: `apps/sessions/turn_driver.py`, `apps/sessions/management/commands/drive_turn.py`, `apps/sessions/tests/test_turn_driver.py`
- Modify: `apps/canopy/run_dispatch.py` (drop the legacy branch from `start_turn`), `config/settings/base.py` (drop `CANOPY_RUN_EXECUTION`), `CLAUDE.md`
- Modify: `apps/opps/tests/test_api.py`, `apps/sessions/tests/test_api.py` — the eight monkeypatches of `start_turn_subprocess` become monkeypatches of `run_dispatch.start_turn`

**This task must not be executed as part of this plan.** Every one of the following must be demonstrably true first. Check them off with evidence, not assertion.

- [ ] **Precondition 1 — a session-capable canopy runner exists and is online.** canopy-side PR 2 (`feat/cloud-runner-sessions`) has shipped, some runner declares `capabilities.sessions: true`, and `GET {canopy}/api/harness/runners/` shows it `online` + `ready`. Until this holds, `claim_next_turn` refuses every session turn and retiring the driver means **no ACE run executes at all, anywhere**.
- [ ] **Precondition 2 — a real ACE run has completed end to end on canopy.** Not a stub, not a drill: a `seeded_run` against a real opp, with `CANOPY_RUN_EXECUTION=True`, reaching canopy `Turn.status = "done"`, with `run_state.yaml` in Drive advanced by the run. Record the opp slug, run id, and canopy turn id in the PR body.
- [ ] **Precondition 3 — `--resume` continuity works across turns.** canopy-side PR 2 also wires `Session.cli_session_id` from the CLI's `system/init` line. Verify a *resume* (`POST /sessions/{slug}/resume`) continues the same CLI session rather than starting cold; a resume that silently starts fresh loses the orchestrator's context and is a regression against `turn_driver`, which already passes `--resume` (`cli_backend.py:812-816`).
- [ ] **Precondition 4 — cost and structure are non-empty for that run.** `GET /{slug}/cost` returns real totals and `GET /{slug}/structure` returns a real tree, both derived from the canopy transcript. If canopy's retained transcript is missing or partial, retiring the local capture path destroys the analyzer.
- [ ] **Precondition 5 — `CANOPY_RUN_EXECUTION=True` has been the production default for at least one full deploy cycle**, including one `resume-interrupted` sweep after an ECS rollout, with no run falling back to the subprocess.
- [ ] **Precondition 6 — the Slack path (Task 11) has shipped and executed at least one run**, or has been explicitly disabled. Retiring the driver while Slack still routes through `start_turn`'s legacy branch would silently break it a second time.
- [ ] **Precondition 7 — decide `CLIBackend`'s fate separately.** `apps/common/cli_backend.py` is still used by `apps/sessions/auto_title.py` and `apps/common/backend_selector.py`. Retiring `turn_driver` does **not** retire it. Scope that as its own change; do not fold it in.

Only when all seven are checked: delete the three files, collapse `start_turn` to `dispatch_turn`, remove the flag, update `CLAUDE.md`'s "the capability it smoke-tested is still real" paragraph, and re-point the eight monkeypatches. One commit, one PR, no other changes in it.

---

## Self-review

**Spec coverage.**

| Spec requirement | Task |
|---|---|
| Item 4 — `seeded_run` enqueues instead of spawning | 3, 4 |
| Item 4 — `resume_run` enqueues instead of spawning | 4 |
| Item 4 — `resume_interrupted` enqueues instead of spawning | 4 |
| Item 4 — the `drive_turn` command | 12 (it is `start_turn_subprocess`'s subprocess entrypoint, not an independent caller — see "what stays, what changes") |
| Item 4 — the Slack path | 11 (not migrated: it never executed. Fixed instead) |
| Item 4 — one canopy Session per opp-run, `session.agent = ace` | 3 (`create_run_session` with `agent_slug=ace`, id on `Session.canopy_session_id`) |
| Item 4 — Turns target the **session**, not the agent | 3 (`POST /canopy-sessions/{id}/send` is the only HTTP route that enqueues a session turn; `POST /harness/turns/` cannot — `TurnIn` accepts `agent_slug` XOR `project` only) |
| Item 4 — `origin_ref` carries `{opp_slug, run_id, step_skill}` | 3, **with a documented divergence**: `SendIn` has no `origin_ref` field, so the linkage rides `session.metadata` (which canopy already filters on) plus `Message.canopy_turn_id` locally |
| Item 4 — retire `turn_driver` last, with explicit preconditions | 12 |
| Item 4 — establish what stays/changes/goes for `Session`/`Message`/`SessionParticipant` | "Critical context" table |
| Item 5 — read canopy's per-turn transcript | 8, 9, 10 |
| Item 5 — do not repeat the multi-member-gzip truncation | 8 (Step 4: refuse any content-encoding; `urllib.request`, never `httpx`) |
| Item 5 — migrate existing local `IngestUpload` rows | 9 (`source="local"` default *is* the backfill; no rewrite, no deletion) |
| Item 6 — explicit "no runner available" state | 5, 6, 7 |
| Item 6 — first-class run state, not an error banner | 5 (`STATES` tuple), 7 (`OppRunsList` badge replaces the `"queued"` fallback) |
| Open question — is the Slack path already dead? | Answered: LATENT (`/ace run <slug>`) / BROKEN (`/ace new`, PDD link). Evidence in "The Slack path: resolved" |

**Type consistency.** `run_dispatch.start_turn(assistant_message_id: int) -> None` is what all four call sites (three in Task 4, one in Task 11) invoke; `dispatch_turn(...) -> str` is the canopy-only inner call and is only invoked from `start_turn` and its own tests. `run_state.execution_state(session) -> dict` and `reconcile_session(session) -> dict` return the identical four-key shape (`state`, `detail`, `canopy_turn_id`, `canopy_session_id`), which is also `GET /{slug}/execution`'s response body and the `RunExecution` TS interface. `sources.session_raw_jsonl(session) -> bytes | None` is the single name used by both `get_structure_tree` and `recompute_cost_from_source`. `IngestUpload.SOURCE_LOCAL`/`SOURCE_CANOPY` are referenced by name, never as bare string literals, outside the model.

**Risks carried deliberately, and why.**

1. **The whole thing is inert without a cloud runner, and the flag is the only thing standing between "works" and "nothing runs".** Mitigated by defaulting `CANOPY_RUN_EXECUTION=False`, by Task 12's seven preconditions, and by Item 6 making the inert state visible rather than silent.
2. **canopy's `unclaimable.kind` is unreliable for ace.** It scopes candidate runners to `paired_by=<calling user>`, and ace's delegated user has paired none — so `kind` will always be `"config"`. Handled by treating `kind` as advisory (Task 5, Step 3) and rendering both states honestly; worth a canopy follow-up but nothing branches on it.
3. **The actor-identity path can 403.** ace-web has no email-domain filter; canopy's token-exchange does. A run owned by a user canopy will not delegate for fails at dispatch — loudly, by design (Task 3, `_actor_email` + `_fail`), rather than silently sitting `pending` the way `start_turn_subprocess` would.
