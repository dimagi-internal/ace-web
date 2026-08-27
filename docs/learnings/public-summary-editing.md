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
| row (header + detail) | `DecisionRow` | same component |
| collapsible group | `DecisionSection` | same component |
| type scale | `dense` (console) | `dense` (console) |
| copy voice | `console` | `partner` |
| **staging** | Redis multi-player buffer + explicit Save | **write-through** |
| **commit mode** | `immediate` | `immediate` — `confirm` only until a name is known |

**The Workbench is the reference implementation.** Jonathan compared the
two surfaces on 2026-08-14 and settled it:

> yeah, the workbench is what I remember and what I want to replicate for
> the decisions

So the public surface *replicates* rather than reinterprets, and a
difference has to be forced to survive. There are exactly four:

1. **Staging.** An anonymous caller has no authenticated WebSocket to
   stage on, and a shared buffer that a member must later "Save" **is**
   the promotion gate this design removed.
2. **Identity**, below — the Workbench reads it off the session.
3. **Voice** — "override reason" is Workbench vocabulary a partner has
   never met.
4. **Layout.** The Workbench is master/detail with a phase rail; the
   summary is a single-column document, so its phases stack as
   collapsible `DecisionSection`s instead of being picked from a sidebar.

Everything else — row anatomy, status-chip derivation, the overridden
tint, the detail grid, the console type scale, pill behaviour — is one
component rendered twice.

### Commit mode follows IDENTITY, not surface

This one shipped wrong on 2026-08-14 and was corrected the same day.
`confirm` was made a property of the public surface, so every one of 42
rows carried a "Save this answer" button:

> that UI looks different than I'm used to seeing in the workbench/phases
> and the interactions between selection new choices and its visual
> clarity is worse than what I was used to — Jonathan

The stated justification was *"asking for a name before someone can even
click a pill would be the barrier this surface exists to remove."* That is
an argument about the **first** edit of a session, when nobody has told us
who they are. It never justified a confirm step on the fortieth row: the
name is typed once and remembered (`reviewerIdentity`), so the barrier was
removed at the start and reintroduced on every row after it. A signed-in
member — whose identity is resolved from the session — never had any
reason to see it at all.

So: **`confirm` iff we do not yet know who is editing.** Anonymous +
no remembered name ⇒ one confirm step that collects it. Everything after
that (and every signed-in member, always) is click-and-done, exactly like
the Workbench.

Two traps found while doing it, both locked by tests:

* **Promote identity on a successful WRITE, not on a keystroke.** Deriving
  "we know who this is" from the name field as it is typed flips the row
  from `confirm` to `immediate` mid-draft and pulls the Save button out
  from under the person aiming at it. `identityKnown` moves on a
  successful submit; a separate `canSubmit` tracks what is typed right now.
* **`immediate` mode has no draft block to hang an error off.** A pill
  click that the server refuses would otherwise just snap back silently,
  so `DecisionAnswerEditor` renders `error`/`busy` outside the draft too.

### Copy is a THIRD axis (`voice`), independent of both

`COPY` used to be keyed by `commitMode`, which silently coupled *when a
change becomes durable* to *who is being spoken to* — so the public
surface could not adopt the Workbench's immediacy without also adopting
the word "override", which a partner has never met. It is now keyed by
`voice` (`console` | `partner`). Field `aria-label`s stay identical across
both voices, and a test asserts it.

`dense` **is** adopted by the public page. An earlier pass reasoned that a
summary page is "a document a partner reads, not a console" and kept the
larger reading scale; Jonathan looked at both surfaces and asked for the
Workbench. Taste arguments lose to a direct comparison.

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

## Phase is the organising structure, not a disclosure

The Workbench organises decisions **by phase** — that is how someone
reasons about where a call came from in the flow. The first version of
this surface grouped by phase only *inside* a collapsed "Show all 42"
disclosure, and lifted the 2 `conflicting` rows out of phase context to
lead the page:

> we should have the decisions better organized into the phases/sections
> like they are in the workbench as well so it's obvious where the
> decisions are coming from in terms of the flow — Jonathan, 2026-08-14

A reader could not see where a decision arose until they expanded
everything. Now the phase sections **are** the page, and they are literally the
Workbench's components: `DecisionSection` (the collapsible card, header
button, chevron and divided list) wrapping `DecisionRow`s, with the
`Phase N` eyebrow + display name from `PhaseTile`, amber for contested
from `EvidenceBadge`, and sky for human-changed from the Workbench's
"N overridden" chip.

One width trap came out of sharing the row: every span in the header
truncates, and `truncate` resolves a flex item's `min-width:auto` to 0, so
in the summary's narrower `max-w-3xl` column the QUESTION — the one thing
a reader is there for — was the item that collapsed to nothing while the
row id and the answer kept their width. `DecisionRow` now caps the id,
lets the answer yield, and gives the question a floor.

What the lead-with-the-conflicts view was protecting is kept without
sacrificing the structure:

* a phase holding a flagged row opens by default, and those rows open
  inside it — so the contested rows are on screen at first paint, **in**
  their phase rather than lifted out of it;
* every other phase collapses to a one-line header with its counts, so 40
  routine rows can't bury the 2 that matter;
* "Worth your eye first" is a **jump list**, not a second rendering of the
  same rows. One decision, one home.

### The phase LABEL must come from the plugin, but may not overrule the run

`decisions.yaml` tags rows with an abbreviation (`3-commcare`), which
humanises to "Commcare" where the Workbench says "CommCare Setup" — two
names for one phase across two surfaces defeats the point of organising by
phase. So `apps/opps/summary.py` reads the label from the plugin's phase
registry (`_phase_display_index`, the same source the Workbench renders
from).

**But `serialize_decision` projects a row's tag onto a phase name by
ORDINAL**, which is silently wrong after a pipeline re-order: ACE's phase 4
used to be OCS setup, so a run that recorded `4-connect` would be
published under "OCS Setup" — a confident, wrong claim about provenance on
a page an outside partner reads. `_registry_label_agrees` therefore takes
the registry's display name only when every word of the row's own tag
appears in it (`connect` ⊂ "Connect Setup" ✓, `connect` ⊄ "OCS Setup" ✗),
and the ordinal always comes from the tag the run wrote. The registry may
make a label **fuller**, never overrule the run.
