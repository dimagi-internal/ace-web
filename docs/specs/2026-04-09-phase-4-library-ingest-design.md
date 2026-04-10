# ACE Web Harness — Phase 4: Library & Ingest Design

**Date:** 2026-04-09
**Status:** Approved for execution.
**Scope:** Design system foundation (light/dark, shadcn/ui), basic library page, JSONL ingest (CLI + endpoint), personal upload tokens. Share tokens, participant management, and workbench↔session integration are explicitly deferred.

**Parent spec:** `docs/specs/2026-04-08-ace-web-design.md` — §4.4, §4.5, §4.6.

---

## 1. Overview

Phase 4 delivers three things:

1. **Design system foundation** — shadcn/ui primitives, CSS-variable design tokens, lucide icons, dark/light theme toggle, and a mechanical refactor of all 22 existing files from hardcoded zinc/white Tailwind classes to semantic tokens.
2. **Basic library page** — a flat session list at `/library` with title search, status filtering, archive/delete, and simple pagination. Not a dashboard or landing page — just enough to prevent sessions from vanishing after the sidebar's 10-item window rolls off.
3. **Ingest system** — `POST /api/ingest/upload` endpoint, `ace-upload` CLI tool, personal bearer tokens for CLI auth, and a JSONL parser that turns Claude CLI session files into `Session` + `Message` rows.

## 2. Decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Share links | Deferred. No UI or endpoints in Phase 4. | Team-only sharing (@dimagi.com) confirmed, but no concrete need yet. Schema (`ShareToken` model) stays from Phase 1. |
| Library query scope | Owner-only for now. | Participant-scoped recommended long-term, but no real multi-player participants exist until Phase 3 ships. Revisit then. |
| Library ambition | Basic. `/library` route, not landing page. | The real session-discovery experience lives inside the Workbench, tied to opps/runs/steps. The library is the fallback for "where's that session from last Thursday." Workbench↔session integration deferred until real usage reps. |
| Upload auth | Personal bearer token issued from `/settings`. | Simpler than OAuth for a CLI tool. Original spec said "gcloud identity token" but we're on AWS now. |
| Imported session resume | Soft hint, not hard disable. First send triggers CLIBackend replay. | The Phase 2 hybrid resume strategy already handles cold starts by replaying from Django. An imported session is just a cold start where the CLI session store doesn't exist. |
| Design system | shadcn/ui + lucide + Tailwind CSS variable tokens + Radix primitives. | AI-maintainable: every AI model has deep training data on shadcn. Components are copied into the repo as editable source. Dark/light via `<html class="dark">` + CSS variables. |
| Participant management UI | Deferred. | Phase 3 adds real multi-player; the natural UX will be clearer then. |
| Frontend tests | Not added. | Workbench shipped without frontend tests. Same precedent. Visual correctness verified manually. |

## 3. Design system foundation

### 3.1 Why this is part of Phase 4

Today the chat page uses light-mode zinc-200/white classes and the Workbench uses dark-mode zinc-950/900 classes. 108 hardcoded color references across 22 files. Adding a theme toggle — or building any new surface that looks like it belongs in the same app — requires a tokens layer first. This lands before any library/ingest UI so everything downstream is built on the new kit.

### 3.2 Stack

- **shadcn/ui** initialized against the existing Tailwind 3.4 + Vite setup. "New York" style, lucide icons, CSS variables on.
- **shadcn components** (copied into `frontend/src/components/ui/`): `button`, `input`, `badge`, `dialog`, `dropdown-menu`, `skeleton`, `sonner` (toasts). Each is editable source, ~50-120 lines.
- **Icons**: `lucide-react`. Replaces all unicode glyphs (`⟳ ▶ ✓ ✗ ⚠ ●`) at refactored call sites.
- **Dependencies added**: `lucide-react`, `clsx`, `tailwind-merge`, `class-variance-authority`, `@radix-ui/react-dropdown-menu`, `@radix-ui/react-dialog`, `sonner`.
- **`cn()` helper** at `frontend/src/lib/utils.ts` — `clsx` + `tailwind-merge` for conditional classes.

### 3.3 Theming

- **CSS variables** in `frontend/src/styles/globals.css` — two blocks: `:root` (light defaults) and `.dark` (dark overrides). Semantic names: `--background`, `--card`, `--foreground`, `--muted-foreground`, `--border`, `--ring`, `--primary`, `--primary-foreground`, `--destructive`, plus custom extensions `--status-ok`, `--status-warn`, `--status-error`, `--status-info` for row glyphs.
- **`tailwind.config.js`** — `darkMode: 'class'` + `theme.extend.colors` mapping semantic names to CSS variables. After this, `bg-card`, `text-foreground`, `text-muted-foreground`, `border-border` are real Tailwind utilities.
- **`ThemeProvider`** — wraps the router root. Default = `prefers-color-scheme`. Toggle persisted to `localStorage`. Sets/removes `.dark` on `<html>`.
- **`ThemeToggle`** — small button in the top nav. Lucide `Sun` / `Moon` icon swap.

### 3.4 Refactor of existing files

Mechanical swap across all 22 files currently using hardcoded zinc/white classes:

| Old pattern | New pattern |
|---|---|
| `bg-zinc-950` | `bg-background` |
| `bg-zinc-900` | `bg-card` |
| `bg-zinc-800`, hover states | `bg-muted` |
| `text-zinc-100` | `text-foreground` |
| `text-zinc-400`, `text-zinc-500` | `text-muted-foreground` |
| `text-zinc-600` | `text-muted-foreground/60` or a secondary token |
| `border-zinc-800`, `border-zinc-200` | `border-border` |
| `bg-white` | `bg-card` |
| `bg-amber-600` (primary actions) | `bg-primary` |
| `border-amber-600` (selection) | `border-primary` |

Lands in its own commit. No functional changes in the same commit. Manual walkthrough of Workbench, ChatPage, AuthCliPage in both themes afterward.

### 3.5 Risk

The 22-file refactor is the largest accidental-regression surface in Phase 4. Mitigation: isolated commit, manual walkthrough, no logic changes mixed in.

## 4. Basic library page

### 4.1 Backend

Changes to `apps/sessions/views.py`:

- **`GET /api/sessions`** — new query params:
  - `q=` — case-insensitive title substring (`title__icontains`).
  - `source=` — filter by `web` or `upload`.
  - `page=` — 1-based, default 1.
  - `page_size=` — default 20, max 100.
  - Response shape changes to `{data: {items: [...], total: int, page: int, page_size: int}}`.
  - Ordering stays `-updated_at`.
  - Stays owner-scoped.
- **`DELETE /api/sessions/<slug>`** — new endpoint. Owner-only. Hard cascade via existing FK `on_delete=CASCADE`.
- Existing PATCH (title/status) and GET detail are unchanged.

### 4.2 Frontend

- **Route:** `/library` → `LibraryPage`. `HomePage` stub stays at `/`.
- **Nav:** "Library" link added to top nav alongside "Opps". "View all →" footer link added to `RecentSessionsSidebar`.
- **Page structure** (built on shadcn primitives + semantic tokens):
  - Header row: "Library" title, `<Input>` search (debounced 300ms), `<Button>` "+ New chat".
  - Filter row: `<Button>` group — Active / Archived / Imported / All.
  - Session list: one row per session. Clickable link to `/chat/<slug>`. Shows title (or "Untitled"), source `<Badge>` (`web` / `upload`), relative updated timestamp.
  - Row hover reveals `<DropdownMenu>`: Rename (inline edit), Archive/Unarchive, Delete (with `<Dialog>` confirm).
  - Prev / Next pagination footer.
  - Loading: `<Skeleton>` rows. Empty: "No sessions yet." Error: retry button.
- **Data layer:** `frontend/src/api/sessions.ts` grows `listSessions({q, status, source, page, pageSize})` and `deleteSession(slug)`. New `SessionListPage` type in `api/types.ts`.

### 4.3 What the library does NOT do

- Cross-message search (title substring only, per spec §7).
- Bulk actions, sort options, saved filters.
- Participant counts, shared badges, message counts.
- Landing-page replacement — `/` stays as `HomePage` stub.
- Workbench↔session integration — deferred until usage reps.

## 5. Ingest system

### 5.1 Upload token issuance

- **Model:** `PersonalToken` in `apps/auth/models.py`. Fields: `token` (hashed via `hashlib.sha256`, `secrets.token_urlsafe(32)` raw), `user` FK, `label` (user-supplied), `created_at`, `last_used_at`, `revoked_at`. Raw token shown once at creation.
- **API:**
  - `POST /api/auth/tokens` — create, returns raw token once.
  - `GET /api/auth/tokens` — list (label, created, last_used — never raw token).
  - `DELETE /api/auth/tokens/<id>` — revoke.
- **Auth backend:** `BearerTokenAuthBackend` in `apps/auth/token_backend.py`. Checks `Authorization: Bearer <token>`, hashes, looks up `PersonalToken`, updates `last_used_at`, resolves to `User`. Only applies when no session cookie is present.
- **Frontend:** `/settings` page with token list and "Create token" `<Dialog>`. Reachable from top nav.

### 5.2 Ingest endpoint

- **Module:** `apps/ingest/` — `apps.py`, `views.py`, `parser.py`, `urls.py`, `tests/`.
- **`POST /api/ingest/upload`** — `multipart/form-data`, single `.jsonl` file. Auth via session cookie or bearer token.
  - `parser.py` reads the JSONL, extracts `cli_session_id` from the init event, maps turns to `Message` rows. Reuses knowledge from `apps/common/cli_event_parser.py` but reads from a file.
  - Creates `Session` (`source=upload`, `status=imported`, `owner=request.user`).
  - Creates `Message` rows with incrementing `turn_index`.
  - Creates `IngestUpload` record (`source_path`, `raw_bytes`, `line_count`, `cli_session_id`).
  - Returns `{data: {session_slug, message_count, cli_session_id}}`.
  - **Duplicate guard:** matching `cli_session_id` on existing `IngestUpload` → 409 Conflict.
- **URL registration:** `path("api/ingest/", include("apps.ingest.urls"))` in `config/urls.py`.

### 5.3 CLI — `ace-upload`

- **Entrypoint:** `pyproject.toml` `[project.scripts]`: `ace-upload = "apps.ingest.cli:main"`. The CLI module is a standalone script that uses `httpx` directly — it does NOT import Django or any Django models. It reads `~/.ace/config.toml` for the server URL and token, constructs the multipart HTTP request, and posts to the ingest endpoint. All Django-dependent logic lives server-side in the endpoint.
- **Implementation** in `apps/ingest/cli.py` (~60-80 lines, `argparse` + `httpx`):
  - `ace-upload <file.jsonl>` — single file upload.
  - `ace-upload <directory>` — all `.jsonl` files, one request each, sequential.
  - Config from `~/.ace/config.toml`: `server` URL, `token`.
  - `ace-upload --configure` — interactive 3-prompt setup, writes config file.
  - Progress to stderr. Exit 0 on all-success, 1 on any failure.
- No retry, no parallelism, no resume. Files are small.

### 5.4 Imported session resume

Imported sessions are **not** permanently read-only. The Phase 2 `CLIBackend` hybrid resume strategy already handles the case where the CLI session store doesn't exist — it replays the full conversation history from Django into a fresh subprocess and captures a new `cli_session_id`.

- `SendBox` shows a soft hint: "This is an imported session — send a message to continue it."
- First send flips `session.status` from `imported` to `active` and triggers the normal send flow.
- `CLIBackend` hits the replay fallback (no local CLI session store for an uploaded file), seeds Claude with the imported history, captures new `cli_session_id`. From there it's a normal live session.

## 6. Testing

### 6.1 Backend (pytest + pytest-django, in-memory SQLite)

- **`apps/ingest/tests/test_parser.py`** — JSONL→Message parsing. Fixtures from `docs/learnings/cli-stream-json-format.md`: simple text, tool use, error, multi-turn. Asserts `turn_index` sequencing, role mapping, `cli_session_id` extraction.
- **`apps/ingest/tests/test_views.py`** — upload happy path, duplicate 409, missing file 400, bearer auth works, session auth works.
- **`apps/ingest/tests/test_cli.py`** — argparse + config loading. Mock `httpx`. Test `--configure` output.
- **`apps/auth/tests/test_tokens.py`** — create/list/delete lifecycle, revoked token 401, `last_used_at` updates, `BearerTokenAuthBackend` resolution.
- **`apps/sessions/tests/`** — DELETE cascade, `q=` search, `source=` filter, pagination.
- **Imported session resume** — mock CLIBackend subprocess, assert history seeded on first send to an imported session.

### 6.2 Frontend

No frontend test framework added. Visual correctness verified manually via dark/light walkthrough.

### 6.3 Rollout

1. Design system foundation commit lands first. Manual walkthrough: Workbench, ChatPage, AuthCliPage in both themes.
2. Library page, ingest backend, personal tokens land after. Each independently useful.
3. `ace-upload` CLI tested locally against `docker compose up` before deploy.
4. Deploy via GitHub Actions, `run_migrations: true` (new `PersonalToken` model, `apps/ingest` registration).
5. Post-deploy: create session, archive it, find in `/library`, search by title, upload `.jsonl` via CLI, confirm it appears, send message to resume, toggle dark/light.

## 7. New files

```
apps/
├── auth/
│   ├── models.py              # MODIFIED: add PersonalToken
│   ├── token_views.py         # NEW: CRUD for personal tokens
│   ├── token_backend.py       # NEW: BearerTokenAuthBackend
│   └── tests/test_tokens.py   # NEW
├── ingest/
│   ├── __init__.py            # NEW
│   ├── apps.py                # NEW
│   ├── cli.py                 # NEW: ace-upload entrypoint
│   ├── parser.py              # NEW: JSONL → Message rows
│   ├── views.py               # NEW: POST /api/ingest/upload
│   ├── urls.py                # NEW
│   └── tests/                 # NEW: test_parser, test_views, test_cli
├── sessions/
│   ├── views.py               # MODIFIED: DELETE, search, pagination
│   └── tests/                 # MODIFIED: new test cases
frontend/src/
├── components/ui/             # NEW: ~7 shadcn component files
├── components/ThemeToggle.tsx  # NEW
├── lib/utils.ts               # NEW: cn() helper
├── pages/LibraryPage.tsx      # NEW
├── pages/SettingsPage.tsx     # NEW: token management
└── styles/globals.css         # MODIFIED: CSS variable tokens
```

Plus: `tailwind.config.js`, `config/urls.py`, `pyproject.toml` updated. One new migration. 22 existing files refactored (token swap only).

## 8. Explicitly deferred

- Share tokens — schema stays, no UI/endpoints.
- Participant management — no add/remove UI.
- Workbench↔session history integration — deferred until usage reps.
- Cross-session body search — title substring only.
- Bulk actions, sort UI, saved filters.
- Landing page redesign — `/` stays as `HomePage` stub.
- Frontend test framework.

## 9. References

- Parent spec: `docs/specs/2026-04-08-ace-web-design.md`
- Phase 2 plan (CLIBackend + hybrid resume): `docs/plans/2026-04-08-2-conversation-engine.md`
- CLI stream-json fixtures: `docs/learnings/cli-stream-json-format.md`
- Phase 1 post-execution corrections: `docs/plans/2026-04-07-1a-foundation.md`
