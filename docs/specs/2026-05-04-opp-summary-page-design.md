# Public per-run opp summary page

**Date**: 2026-05-04
**Status**: Design — pending approval before implementation plan
**Owner**: Jonathan Jackson

## Background

Successful end-to-end ACE runs now produce a complete deliverable pack
under `ACE/<opp>/runs/<run-id>/` in Drive: two CommCare apps deployed
on HQ, a Connect opportunity wired up, a training pack (Slides deck +
LLO/FLW guides + quick reference + FAQ), and an OCS support chatbot
trained on the run's content.

The existing Workbench at `/w/<workspace>/opps/<slug>/runs/<run-id>` is
optimized for ACE-team review of *how* the run was built — phases,
skills, gates, judge verdicts, scorecards. That density is the right
tool for QA but the wrong tool when an internal-but-not-ACE-team person,
or an external partner / LLO, just wants to see *what was produced and
where to find it*.

This spec adds a separate **per-run summary page** designed for that
audience. It is a synthesis of links over Drive content — no new
persisted data, no plugin coordination required.

## Goal

Ship a **public, per-run** summary page at:

```
/opps/<workspace-slug>/<opp-slug>/runs/<run-id>/summary
```

that, with no ACE jargon, shows what the run produced and links out to
each deliverable's natural home (Nova, CommCare HQ, Connect, Drive,
OCS).

The page is meant to be sharable as-is — paste the URL into an email,
open it without logging in, scan it in 30 seconds, click through to
the thing you actually need.

Visual reference: `docs/specs/mockups/2026-05-04-opp-summary-page/editorial-v6.html`.

## Non-goals

- **Iteration loop.** Capturing answers to open questions and writing
  them back into `inputs/` for the next run, deciding what other
  artifacts belong in `inputs/`, and any UI for "prepare next run" —
  all explicitly **out of scope**. They get their own spec.
- **Closeout outcomes.** Cycle grade, learnings, LLO feedback summary,
  invoice — intentionally **not** on the public summary. Anything
  internal-only stays in the Workbench.
- **Inline OCS rendering or eval data.** The OCS widget is mounted via
  the OCS-shipped web component; ace-web does not host its own chat UI.
  Eval verdicts and judge scores remain a Workbench concern.
- **Dedicated `/chatbot` standalone route on ace-web.** The popup
  widget covers in-page interaction; the `Open in OCS →` deep link
  covers focused interaction. No third surface.
- **A separate `/summary` route for opps that have no run yet.** The
  page is per-run; if no run has produced artifacts, there's nothing
  to show.

## Audience and visibility

Public-by-URL. No authentication, no share-token gate. Workspace slug
+ opp slug + run id are the only protection — and they're guessable
enough that this is "anyone with the URL," not "secure." That posture
is acceptable because the page deliberately surfaces only links to
already-public-or-handoff-ready artifacts:

- Nova links route through Nova's own auth.
- CommCare HQ links route through HQ's auth.
- Connect links route through Connect's auth.
- Drive links honor Drive's per-doc sharing.
- The OCS chatbot is anonymously available by design (it's the
  anonymous widget API).
- The Open Questions doc honors Drive's per-doc sharing.

If we later need to put confidential content on a per-opp surface, it
goes behind the existing workspace-auth Workbench, not on this page.

## URL shape

**SPA route** (registered in `frontend/src/router.tsx`):

```
/opps/<workspace>/<slug>/runs/<run_id>/summary
```

**JSON API** (registered in `apps/opps/urls.py`):

```
GET /api/opps/public/<workspace>/<slug>/runs/<run_id>/summary
```

Both auth-exempt. Both registered in `config/urls.py` **before** the
SPA catch-all (which is `login_required`), so unauthenticated users
reach the page directly.

Workspace slug is in the path because opp slugs are workspace-scoped
and the public path needs to be self-contained — there's no logged-in
user to resolve workspace via the existing `X-ACE-Workspace` header
pattern.

404 for any of (workspace not found, opp not found, run not found)
returns the same shape so the API doesn't leak which piece is the
miss.

## Page structure

The page is five sections plus a hero and a footer. Every section is
visually identical: a small uppercase section heading, then a list of
rows. Each row is `label · name · link(s)`. The repetition is the
design — it makes the page feel like an index, not a dashboard.

1. **Hero** — opp display name (large), one-line description, status
   pill, end date.
2. **CommCare apps** — one row per app (Learn, Deliver). Two action
   links per row: `Open in Nova →`, `Open in CommCare HQ →`.
3. **Connect opportunity** — one row for the opp, one row for the
   program. Each links out with `Open on Connect →`.
4. **Training pack** — one row per document. The Slides deck gets the
   first row labeled `Deck`, with `Open in Slides →`. The doc rows
   (LLO guide, FLW guide, quick reference, FAQ) each link out with
   `Open →`.
5. **Support assistant** — one row, with copy describing what the bot
   was trained on, and an `Open in OCS →` deep link. The OCS widget is
   *also* mounted on the page as a corner-bubble popup (covered
   below).
6. **Open questions** — one row, linking to the `open-questions.md`
   Drive doc with `Open in Drive →`. No inline rendering of the
   questions (we don't parse the doc body).
7. **Footer** — `Generated by ACE · run <run-id>` on the left, and a
   small `See the full build process →` link to the existing Workbench
   on the right.

Sections render only if their backing artifacts exist. A run that
hasn't reached Phase 4 yet shows the Apps + Connect + Training rows
that *do* exist and omits the Assistant + Open Questions sections
(rather than displaying placeholders for missing data).

## Data sources

All section content is derived live from the run's Drive folder. No
new persisted data, no plugin contract change.

| Section | Drive source | Field(s) read |
|---|---|---|
| Hero — name | `opp.yaml` (opp root) | `display_name` (fallback to slug) |
| Hero — description | `runs/<run_id>/pdd.md` | first paragraph after H1 |
| Hero — status | `runs/<run_id>/run_state.yaml` + `connect-setup/opportunity.md` | derived: see "Status" below |
| Hero — end date | `connect-setup/opportunity.md` | `end_date` |
| Apps — Learn name | `app-summaries/learn-app-summary.md` | `display_name` (or first H1) |
| Apps — Learn Nova URL | same | frontmatter `nova_app_url` |
| Apps — Learn HQ URL | `deployment-summary.md` | best-effort regex extraction of the Learn-app HQ build URL (the file is markdown the plugin writes; format is stable but not contractually structured for ace-web — a missing URL renders the row without that link rather than failing) |
| Apps — Deliver | `app-summaries/deliver-app-summary.md` + `deployment-summary.md` | mirror of Learn |
| Connect — opp name + dates | `connect-setup/opportunity.md` | `name`, `start_date`, `end_date` |
| Connect — opp URL | same | computed from `opportunity_id` (`https://connect.dimagi.com/o/opportunities/<id>/`) |
| Connect — program | `connect-setup/program.md` | `name`, computed program URL |
| Training — deck | `runs/<run_id>/run_state.yaml` | `training_deck.web_view_link`, derived title |
| Training — docs | `training-materials/*.md` Drive listing | filename → friendly title; `web_view_link` |
| Assistant — link | `ocs-setup/widget-handoff.md` | `widget_url` (preferred); fall back to `ocs-agent-config.md` `public_id` + a configured OCS host |
| Assistant — widget mount | `ocs-agent-config.md` | `public_id`, `embed_key` |
| Open questions — link | `open-questions.md` (opp root) | Drive `web_view_link`; section omitted if file absent |

**Status derivation** (hero pill):

- `closed` if the run's `closeout/cycle-grade.md` exists.
- `active` if `connect-setup/opportunity.md` exists and its `end_date` is in the future.
- `in_progress` otherwise.

This is the only computed field on the page; everything else is a
direct read.

## JSON payload shape

The frontend hydrates from a single endpoint. Shape:

```jsonc
{
  "opp": {
    "workspace_slug": "dimagi-team",
    "slug": "turmeric-supplementation-pilot",
    "run_id": "20260415-1430",
    "display_name": "Turmeric Supplementation",
    "description": "A maternal-health pilot in two districts of Bihar.",
    "status": "active",         // "active" | "closed" | "in_progress"
    "end_date": "2026-06-15"
  },
  "apps": [
    { "kind": "Learn",   "name": "...", "nova_url": "...", "hq_url": "..." },
    { "kind": "Deliver", "name": "...", "nova_url": "...", "hq_url": "..." }
  ],
  "connect": {
    "opportunity": { "name": "...", "url": "...", "start_date": "...", "end_date": "..." },
    "program":     { "name": "...", "url": "..." }
  },
  "training": {
    "deck": { "title": "...", "url": "..." } | null,
    "docs": [ { "title": "LLO manager guide", "url": "..." }, ... ]
  },
  "assistant": {
    "ocs_url":   "...",   // OCS standalone chatbot URL — see "OCS URLs" below
    "public_id": "...",   // for the widget
    "embed_key": "..."    // for the widget
  } | null,
  "open_questions": {
    "url": "https://docs.google.com/document/d/.../edit"
  } | null,
  "workbench_url": "/w/dimagi-team/opps/turmeric-supplementation-pilot/runs/20260415-1430"
}
```

Top-level fields are independently nullable. The frontend renders only
the sections whose data exists.

## OCS URLs

Two OCS-hosted URLs the page needs:

1. **Standalone chatbot URL** for the body section's `Open in OCS →`
   link. Preferred source: `widget_url` in
   `ocs-setup/widget-handoff.md`. If the handoff doc isn't yet
   present (early-Phase-4 runs), the implementation may construct one
   from `ocs-agent-config.md`'s `public_id` against
   `ACE_OCS_PUBLIC_BASE` (default `https://chatbots.dimagi.com`); the
   exact path component (e.g. `/c/<public_id>/`) is to be confirmed
   against a live OCS instance during implementation, not guessed in
   the spec.
2. **Widget script origin** for the corner-bubble web component. From
   `ACE_OCS_WIDGET_HOST` (default `https://chatbots.dimagi.com`).

If neither URL can be resolved, omit the section.

## OCS widget mounting

The summary page mounts the standard OCS web component as a
corner-bubble popup:

```html
<script src="https://chatbots.dimagi.com/static/widget.js" async></script>
<open-chat-studio-widget public-id="..." embed-key="..."></open-chat-studio-widget>
```

The script + tag are conditionally rendered: only when
`payload.assistant` is non-null. The widget self-positions and brings
its own styling — ace-web does no chrome around it.

The OCS widget script's exact origin is configurable via
`ACE_OCS_WIDGET_HOST` (default `https://chatbots.dimagi.com`) so we
can point at a staging OCS host without code changes.

## Backend

All under `apps/opps/`.

- **`apps/opps/summary.py`** (new). Pure composition:

  ```python
  def build_summary_payload(
      drive: DriveClient,
      workspace,
      opp_slug: str,
      run_id: str,
  ) -> SummaryPayload | None:
      ...
  ```

  Returns `None` when the run folder doesn't exist. No I/O outside the
  `drive` client. Easy to unit-test against `fake_drive`.

- **`apps/opps/sync.py`** — extend with a smaller `load_summary(...)`
  helper that reads only the artifacts the summary needs. The existing
  full-Workbench loader is too expensive for a public-traffic
  endpoint. Reuses the manifest-driven file→skill attribution that
  already lives in `parsers.py`.

- **`apps/opps/views.py`** — new `public_opp_summary(request,
  workspace, slug, run_id)` view. Auth-exempt. Calls the loader →
  `build_summary_payload` → `success_response(payload)`. Always
  returns a 404 envelope on the same shape regardless of which segment
  was missing.

  Caches the JSON payload via Django's cache backend for ~60 seconds
  keyed on `(workspace, slug, run_id)` so a viral share doesn't
  translate to N Drive reads per second. Cache invalidation is the
  60s expiry — matches the rest of the Workbench's read-through
  posture. **404 responses are not cached** so a freshly-published
  opp / run becomes visible immediately rather than after the TTL.

- **`apps/opps/urls.py`** — register
  `public/<workspace>/<slug>/runs/<run_id>/summary`.

- **`config/urls.py`** — add an explicit non-`login_required` SPA
  shell route:

  ```python
  re_path(
      r"^opps/(?P<workspace>[^/]+)/(?P<slug>[^/]+)/runs/(?P<run_id>[^/]+)/summary/?$",
      TemplateView.as_view(template_name="index.html"),
      name="public_opp_summary",
  ),
  ```

  Placed before the existing `r"^(?!api/|admin/|auth/|...)"` SPA
  catch-all, so it wins.

## Frontend

All under `frontend/src/`.

- **`pages/OppSummaryPage.tsx`** — fetches
  `/api/opps/public/<workspace>/<slug>/runs/<run_id>/summary`,
  composes the page from sub-components.

- **`router.tsx`** — register the route at top level (workspace-agnostic):

  ```tsx
  { path: "opps/:workspace/:slug/runs/:runId/summary", element: <OppSummaryPage /> },
  ```

  Sibling to the existing `share/:token` public route.

- **`components/opps/summary/`** — small, focused components:
  - `SummaryHero.tsx`
  - `SummarySection.tsx` — uppercase heading + children rows
  - `SummaryRow.tsx` — `label · name · links` row primitive
  - `OcsWidgetMount.tsx` — injects the script tag once + mounts the web component element

- **No new shadcn primitives.** All styling uses existing tokens
  (`text-foreground`, `text-muted-foreground`, `bg-card`,
  `border-border`, `--status-ok`) and existing components (`Badge`
  for the status pill).

- **No invented colors, gradients, or animations.** The mockup at
  `docs/specs/mockups/.../editorial-v6.html` introduced an amber
  accent, a hero gradient, and a pulsing status dot — those are
  mockup artifacts, **not** the implementation target. The real
  page uses the project's monochrome palette and stillness; layout
  and typography carry the visual weight.

- **Geist** is already loaded site-wide via
  `@fontsource-variable/geist` — no font additions, no Google Fonts.

## Error handling

- **Run / opp / workspace not found** → public 404 page rendered by
  the SPA. Same UX regardless of which piece was missing.
- **Drive read failure** → render the page with a soft banner ("Some
  content is temporarily unavailable") and whatever sections did
  succeed. Don't 500 the whole page on a single artifact read failing.
- **Missing OCS embed credentials** → omit the Support assistant
  section entirely. Don't attempt to mount a broken widget.
- **OCS widget script load failure** → silently no-op (the widget is
  async, non-essential to the page); the body's `Open in OCS →` deep
  link still works.

## Testing

- **Unit** — `build_summary_payload` against fake_drive fixtures
  covering: complete run (every section populated), Phase-2-only run
  (apps + training but no Connect/OCS), and totally empty run
  (returns `None` → 404). Frontmatter parsing edge cases (missing
  fields, malformed YAML) covered with a small fixture set.

- **Unit (status derivation)** — explicit cases for `closed`,
  `active`, `in_progress`.

- **Integration (Django)** — `pytest` test that hits
  `/api/opps/public/...` anonymously and asserts (a) the response is
  200 (no auth redirect), (b) the envelope shape matches, (c) a
  non-existent run returns 404, (d) cache hit on second call within
  60s avoids a Drive call.

- **Integration (SPA shell)** — assert that
  `/opps/<workspace>/<slug>/runs/<id>/summary` returns the SPA
  template anonymously (no `/auth/login` redirect).

- **Manual smoke** — load the summary page on a real completed opp
  (e.g., `turmeric-supplementation-pilot` once it lands in Drive),
  confirm the OCS widget mounts, all links open the right targets,
  and the page renders correctly in light + dark mode.

## Out-of-scope follow-ups

These are intentionally not part of this spec; capturing here so they
don't get lost:

1. **Iteration loop spec.** How answers to `open-questions.md` round-trip
   into `inputs/` for the next run. What other artifacts belong in
   `inputs/`. Whether ace-web should grow a "prepare next run" surface
   or leave it as a Drive-only flow. Owner: Jonathan, separate spec.

2. **Per-opp summary** (vs. per-run). If the team ends up wanting a
   "this is the latest run's summary at a stable URL" link, that's a
   tiny shim over this work — define a redirect from
   `/opps/<workspace>/<slug>/summary` → the latest run's summary
   page. Defer until asked.

3. **Closeout-specific surfaces.** A workspace-auth-protected closeout
   review page that *does* show cycle grade, LLO feedback, and
   invoices — distinct from this public surface. Defer until asked.
