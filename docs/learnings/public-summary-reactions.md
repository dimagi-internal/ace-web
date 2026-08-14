# Partner reactions on the public run summary

**Status:** shipped 2026-08-14. **Partly superseded the same day** — the
"an anonymous self-asserted name must not silently rewrite the next run's
inputs" rule below was overruled by Jonathan and decision rows are now
editable in place by anyone with the link. See
[public-summary-editing](public-summary-editing.md). Everything here about
COMMENTS (the feedback-ledger store, the `public-` slug marker as a
confidentiality boundary, the identity model, the abuse controls) still
holds; comments and edits coexist as different acts.
**Code:** `apps/opps/reactions.py`, `apps/common/rate_limit.py`,
`frontend/src/components/opps/summary/DecisionReactions.tsx`.

The public per-run summary shows a partner every load-bearing call ACE made
(42 rows on `spark-facilitator/20260813-2126`, two of them `conflicting`).
Until this landed there was no way to say anything about any of them — which
reproduces the failure the decisions log exists to fix (people skim a 24-page
PDD and agree with all of it), just in a nicer shape.

## Where a reaction goes, and the two paths it deliberately is NOT

ace-web already had two write paths for a human's response to a run. Neither
fits, and the reasons are worth keeping:

| Path | What it records | Why not this |
|---|---|---|
| `POST /{slug}/gates/{skill}` | a MEMBER's approve/reject of a SKILL, into `run_state.yaml`'s `gates:` | wrong grain (skill, not row), wrong vocabulary (binary), wrong identity (authenticated member), and it writes the file the ACE plugin's Phase Write-Back Contract owns |
| `inputs/decision-overrides.yaml` (`apps/opps/decision_overrides.py`) | a MEMBER **changing** an answer; read by the next run as design input | a self-asserted name on an unauthenticated page must not silently rewrite the next run's inputs. An override is a decision; a partner reaction is evidence a human might decide on |

So a reaction is a **feedback record** — the store the ACE plugin's
`skills/feedback-ledger` already defines for an external reviewer's verbatim
comment, with a `<record-slug>/<item-id>` provenance stamp (`Feedback-Ref:`)
that every downstream change cites and a completeness property that renders an
unactioned item as **UNROUTED** rather than dropping it. Writing in that shape
means the next run's ledger picks the comment up with no new consumer, and a
member can still promote it to an override through the Workbench path above.

## The strict-schema constraint

`FeedbackRecordSchema` (`lib/feedback-ledger.ts`, schema_version 1) is a
**strict** zod object — no extra keys. Everything this surface needs to say
about itself is therefore encoded in fields the schema already has:

- `slug` = `<YYYYMMDD>-public-<reviewer-slug>`. The `public` segment is the
  marker: it distinguishes a self-reported name on an anonymous page from a
  verified gdoc comment **in the fact store itself**, and it is what
  `read_reactions` filters on. `skills/feedback-ledger` writes privately
  captured reviews (email, meeting, gdoc comments) into the *same folder*;
  without the marker a confidential review could be republished on a page
  anyone can open. Test: `test_a_privately_captured_review_is_never_republished`.
- `channel: other` — the enum has no `public-summary` member. Adding one is a
  plugin-side change (dimagi-internal/ace).
- `artifact` names the surface and says the identity is self-reported.
- `anchor` = `decision:<decision-id> · <question>` — parseable back to the row
  (there is nowhere else to put a foreign key), legible in the rendered ledger.
- item `id` = the decision id, so a stamp reads
  `20260814-public-anne-kuhlmann/solicitation-expected-period`.

A reaction naming a decision id that isn't in the run's `decisions.yaml` is
**refused**, not stored: the ref would dangle and render under the ledger's
"Broken stamps".

## Identity: a required, self-reported name

The page has no login and a partner cannot self-serve one (ace-web rejects
non-@dimagi.com sign-ins at the OAuth callback). The real options were a
required free-text name or anonymous comments. Anonymous defeats the store it
lands in — the ledger's value is telling a reviewer where *their* comment went
and telling a future reader whose judgement drove a change. So: name required,
email optional (the reply path, never served on the public payload), and the
record says the name is **self-reported** rather than pretending it is
verified. The browser remembers the name locally so working through several
rows costs one typing.

## Abuse controls on a public write endpoint

Four ceilings, because there is no account to attribute an over-limit to:

- per-IP burst (8 / 10 min) and per-IP day (40), on the Django cache,
  **fail-open** — a Redis blip must not lock a real reviewer out.
  `X-Forwarded-For`'s first entry is the client the labs ALB saw; it is
  spoofable, which is why the other ceilings exist.
- per-record (50 items) and per-run (300 items across every public record), so
  a rotating actor cannot balloon a Drive file.
- Length caps enforced twice: the pydantic schema before any Drive round-trip,
  then the writer.
- HTML is **rejected, not stripped**. React escapes on render, but the text
  also lands in a YAML file the ledger renders into a Google Doc via markdown —
  and silently mangling a reviewer's words is worse than refusing them.

## Two traps worth remembering

1. **The write path must go through `CachedDriveClient`** (with `bypass=True`:
   reads skip the 30s TTL, writes still invalidate it). A raw
   `get_drive_client` leaves the read path serving a cached folder listing
   without the record just written, and the reviewer's comment looks lost for
   half a minute. The `opp-summary:v2:*` payload cache is invalidated too —
   `_summary_cache_key` is shared by the read and write paths so they cannot
   drift.
2. **Reactions ride the summary payload**, not a second fetch. A separate
   request means the empty state renders first, and "nobody has said anything"
   is a lie the page tells while the second request is in flight.

## Tabs, and why the URL family didn't change

The decisions log is the part of the page a partner can react to, and burying
42 rows two screens under the artifact links made it the last thing anyone
reached. It is now a **tab** (`?tab=decisions`) on the same URL — a partner
still gets ONE link, and can be pointed straight at the part that needs them.
The strip is the Workbench's own `ViewSwitcher` (generalised over the tab key
so the summary's tabs don't widen `ViewKind`) driven by `useUrlTab`, the hook
`useViewMode` now delegates to. No second tab implementation.
