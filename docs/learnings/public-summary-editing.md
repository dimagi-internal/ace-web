# Editing decisions from the public run summary

**Status:** shipped 2026-08-14. Supersedes the "reactions only" model in
`public-summary-reactions.md` (still accurate about comments).
**Code:** `apps/opps/decision_overrides.py`, `apps/opps/public_input.py`,
`apps/opps/api.py::public_decision_edit`,
`frontend/src/components/opps/decisions/*`.

## The ruling

#710 shipped per-row **comments** and explicitly refused to let the public
page write `inputs/decision-overrides.yaml`, on the grounds that "an
anonymous self-asserted name must not silently rewrite the next run's
inputs". Jonathan overruled that the same day:

> we definitely want the decisions UI to be editable by users … we don't
> even need to have the promotion gate, we do need to have reviewer 2 can
> change / update reviewer 1 anyways in the UI, and that should just be
> the same as Dimagi going in and updating things on top of the anonymous
> input (also **if you are logged in, obviously should not be anonymous**)

The constraint behind it: **the bar to start engaging with ACE has to be
very low, because it is speculative AI work.** An account requirement is a
barrier; a name field is not.

The reasoning is coherent and shouldn't be re-litigated. The PDD that
these decision rows summarize is *already* world-editable via
anyone-with-link, and already seeds the next run. Gating the decisions UI
more tightly than the design document itself was backwards.

**Safety here is visibility and reversibility, not permission** — the same
property a Google Doc runs on. That is why attribution and history are
load-bearing rather than nice-to-have: if the history stops being visible
and undoable, the model stops being safe.

## One store, two surfaces

The Workbench already had editable decisions for authenticated members:
WebSocket `decision.edit` → `decisions_buffer` (Redis) → an explicit "Save
to Drive" → `<opp>/inputs/decision-overrides.yaml` → the plugin's
`decisions_append_rows` binds them on the next run (ace#933). That IS
"Dimagi going in and updating things", so the public tab uses it rather
than a parallel anything.

| | Workbench | Public summary |
|---|---|---|
| store | `inputs/decision-overrides.yaml` | same file |
| merge + serializer | `merge_overrides` / `render_overrides_yaml` | same functions |
| write | `write_override_rows` | same function |
| row builder | `make_override_row` | same function |
| read | `fetch_saved_overrides` | same function, `include_email=False` |
| editor UI | `DecisionAnswerEditor` | same component |
| option pills | `OptionPills` | same component |
| identity fields | n/a (session) | `ReviewerIdentityFields` |
| **staging** | Redis multi-player buffer + explicit Save | **write-through** |
| **commit mode** | `immediate` | `confirm` |

Only the last two rows are surface-specific, and both are forced:

* An anonymous caller has no authenticated WebSocket to stage on, and a
  shared buffer that a member must later "Save" **is** the promotion gate
  this design removed.
* `confirm` exists because the identity is collected at submit. A pill
  click can't be instantly durable when we don't yet know who clicked it —
  and asking for a name *before* someone can click is the barrier the
  whole surface exists to remove.

Copy differs by mode (`COPY` in `DecisionAnswerEditor`): "Override reason"
is the Workbench's established vocabulary and matches the field it writes;
a partner reading a summary page has never met that word. Field
`aria-label`s stay identical across both.

## Identity

`apps/opps/public_input.resolve_reviewer` is the single answer:

* **Signed in ⇒ never anonymous.** The session identity wins and the
  body's typed name is *discarded*, not merged — two names on one change
  is worse than one. The UI doesn't render the name field at all.
* **Not signed in ⇒ a required self-reported name**, asked at submit,
  remembered in `localStorage` so working through several rows costs one
  typing (shared with the comment box — one identity per visit).

The distinction is stored as `decided_by_verified` and rendered, never
enforced. A member's edit has no more authority than a partner's.

**Attribution is CSRF-gated even though the write is not.** The endpoint is
`csrf_exempt` (django-ninja's default) because it must accept a genuinely
anonymous POST. That's fine for the write — anyone may edit — but without
a check, a third-party page could make a signed-in member's browser file a
change under *their* name. So the session identity is claimed only when
the request also passes Django's normal CSRF check
(`session_identity_is_trustworthy`); otherwise it falls back to the
anonymous path, which then asks for a name. Degrade, don't reject.

## Row shape (schema_version stays 1)

Added, all optional: `decided_by_name`, `decided_by_verified`, and
`history` (newest-first snapshots, capped at `MAX_HISTORY_PER_ROW`).

`schema_version` must stay **1**: the plugin's `parseDecisionOverridesYaml`
fail-louds on any other version, and `DecisionOverrideRowSchema` is a
*non-strict* zod object, so it strips fields it doesn't know. Additive
fields are safe; a version bump is not, without a paired plugin change.

**History is derived on merge, never accepted from a writer** — otherwise
a public caller could erase the trail that makes their own edit
reviewable.

**A revert is now a row, not an absence.** `merge_overrides` used to drop
a row whose value was back to the AI default with no reasoning ("revert
leaves no trace beyond absence"). It now keeps such a row whenever it has
history, so "someone reverted this" stays visible and undoable. The plugin
skips a no-op row by construction (`applyDecisionOverrides`), so it is
inert for the next run either way.

## Comments and edits both exist

They are different acts and each row shows both:

* An **edit** asserts a value. It changes what the next run builds from
  and lands in `inputs/decision-overrides.yaml`.
* A **comment** is discussion — a question, a doubt, missing context. It
  lands in the feedback ledger with the `Feedback-Ref` stamp downstream
  changes cite, and renders as **UNROUTED** if nobody acts on it.

Collapsing them costs something real in both directions:
comments-only was the promotion gate that just got removed;
edits-only would force anyone with a *question* to assert an *answer*.
On a conflicting row the comment prompt is therefore sharpened to name
the other act: *"Not sure enough to change it? Say what you'd want to
know."*

The `public-` slug marker on feedback records is untouched, and so is the
test asserting a privately-captured review is never republished.

## Abuse controls

Carried over from the comments surface, and now **one shared per-IP
budget** across both public write endpoints — two endpoints with separate
budgets is just double the budget. Raised from 8/10min (comments only) to
20/10min + 100/day, because a reviewer working the flagged rows plus a
pass over 42 rows plausibly makes 10–20 writes in a sitting, and a limit
that stops a real reviewer mid-review is the barrier this surface exists
to remove. Fail-open on a cache blip.

Still in force: HTML **rejected, not stripped**; control characters
stripped; length caps enforced twice (pydantic before any Drive
round-trip, then the writer); per-record and per-run item ceilings on
comments; `MAX_HISTORY_PER_ROW` on edits. And: **an edit naming a decision
id the run's `decisions.yaml` does not carry is refused, not stored** —
the plugin binds overrides by `id` as a run raises rows, so an id no run
raises is a silent no-op that reads to its author like a change they made.

Writes go through `CachedDriveClient(bypass=True)` and invalidate the 60s
summary payload cache, for the same reason as comments: a change that
takes a minute to appear reads as a change that was lost. The POST returns
the merged row so the page re-renders immediately.
