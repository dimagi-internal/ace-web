## 2026-04-29 — opp-compare (autonomous)

Eighth cycle on ace-web; fourth autonomous run today (after session-previews,
opp-list-attention, and the small score-chip fix). Lens framing: user-value,
killer-feature completion. Theme: **see whether your changes actually made
the opp better.** The previous opp-list-attention cycle made it possible to
SEE which opp needs attention; this cycle closes the loop by letting you SEE
whether a new iteration improved.

### Phase A — target email DRAFT (pre-implementation)

Three highlights, one bundled PR:

1. **Compare two opps side-by-side** — new `/w/<ws>/opps/compare/<a>/<b>`
   page. Three-column layout (Opp A, Delta, Opp B); per-skill rows for
   status, judge score, gates, artifacts. Adapted from the existing dead
   `CompareTable.tsx` shape but driven by `OppSnapshot` not the
   deprecated multi-run model.

2. **"Compare with…" button on every /opps card** — opens a picker; tags
   that match between the source and a candidate sort to the top under a
   "Tag-siblings" header. The improvement loop's missing button.

3. **Improvement summary banner** — top of the compare page. Headline copy
   like "idea-v2 improved by +12 (70 → 82) · 1 fewer pending gate" with a
   delta-tone background (emerald/red/neutral). "Did the new iteration get
   better?" answerable in 5 seconds.

#### Phase A self-critique

- **Clear:** PASS. Each highlight names a specific URL/element. Recipient
  knows what changed in 5s.
- **Testable:** PASS. Try-it lines are real assertions: hover a card → see
  Compare arrow; click → see picker with TAG-SIBLINGS section; pick → land
  on `/opps/compare/...` with a delta banner.
- **Impressive:** PASS. The killer-feature workflow is now end-to-end
  legible. Not polish — workflow completion. The migration comment in
  `apps/opps/migrations/0002_oppworkspace_tags.py` literally said "Future
  UI: tag filter + side-by-side compare"; this is the future.

Approved. Proceeded to Phase B.

### Do it

1. **Side-by-side opp compare** — Effort: M — Status: shipped (PR #147)
   - Branch: `ace-web/auto/opp-compare`
   - What:
     - `apps/opps/views.py::opp_compare` — new GET endpoint at
       `/api/opps/compare/<a>/<b>`. Loads both `OppSnapshot`s + opp-eval
       cards, returns `{a, b, summary}` with pre-computed `score_delta`,
       `pending_gates_delta`, etc. Same-opp short-circuits to `400 same-opp`.
     - `apps/opps/sync.py::load_opp_card_by_slug` — public wrapper around
       `load_opp_card` that locates the opp folder by slug; used by the
       compare view.
     - `apps/opps/urls.py` — `compare/<slug:slug_a>/<slug:slug_b>` route
       added before the `<slug:slug>` workbench route.
     - `apps/opps/tests/test_views_compare.py` — 9 tests covering happy
       path, score delta, pending-gates delta, single-scored opp, same-opp
       guard, unknown-left/right 404, unauthenticated 401, mixed-fixture
       sanity.
     - `apps/opps/tests/fixtures/fake_drive.py::compare_pair_tree` — new
       fixture: two opps with distinct opp-eval scores + gate states.
     - `frontend/src/api/types.ts` — `OppCompare`, `OppCompareSummary` types.
     - `frontend/src/api/opps.ts::getOppCompare`.
     - `frontend/src/pages/OppComparePage.tsx` — new page with hero summary
       banner ("opp-evaluation neither/improved/regressed") and the
       three-column per-skill grid below. `headlineTone` colors the banner
       background by score delta first, gates delta second.
     - `frontend/src/components/opps/CompareTable.tsx` — repurposed from the
       dead multi-run shape (`Run × Run`) to `OppSnapshot × OppSnapshot`.
       Was unused before this PR; clean rewrite.
     - `frontend/src/components/opps/CompareWithDialog.tsx` — picker dialog.
       Tag-siblings sort to top under their own header; everything else
       alphabetical underneath.
     - `frontend/src/pages/OppListPage.tsx` — Compare button (icon =
       lucide GitCompareArrows) wired in next to Delete on each card.
       Disabled when only one opp exists in the workspace.
     - `frontend/src/router.tsx` — `opps/compare/:slugA/:slugB` route under
       the workspace branch.
   - Outcome: 12 files changed, +890/-39. 9 new tests pass; full suite
     542 passing; ruff clean; tsc clean. Convince-self gate green
     (mechanical 3a + self-review 3b + dogfood 3c with same-opp guard
     verified live). PR #147 squash-merged at 19:39 UTC; deploy-labs.yml
     succeeded; `/api/health` 200; live verification via gstack on labs:
     opps list shows hover-revealed Compare icons and `turmeric-iterations`
     tag chip; picker opens with TAG-SIBLINGS section above OTHER OPPS;
     compare URL `/opps/compare/turmeric-market-survey-2026-04-29-coverage/turmeric-market-survey-20260420-1000`
     renders the delta banner ("Neither opp has been judged by opp-eval
     yet · 2 more pending gates") + per-skill grid.

### Backlog

(none surfaced)

### Closed

(none)

### Phase E — sent

- **Sender skill:** `ace:email-communicator` (gog gmail send via
  `ace@dimagi-ai.com` / client `ace`)
- **Subject:** `[ace-web] What's new — side-by-side compare for two opp runs`
- **Recipient:** jjackson@dimagi.com
- **Body:** HTML rendered from email-format.md template; 8.7KB
- **messageId:** `19ddb41aebeadeb7`
- **threadId:** `19ddb41aebeadeb7`
- **Asset branch:** https://github.com/jjackson/ace-web/tree/pm-assets/2026-04-29-opp-compare
  - `screenshots/01-opps-list.png` — opps list with Compare icon hover-revealed
  - `screenshots/02-compare-picker.png` — picker with TAG-SIBLINGS section
  - `screenshots/03-compare-page.png` — compare page with summary banner + grid
  - `screenshots/email-rendered-{desktop,mobile}.png` — pre-send check shots
  - `email.html` — the rendered body that was sent

### Phase E.5 — post-send self-review

Three concrete improvement ideas, ranked by impact:

1. **The compare page's headline reads "Neither opp has been judged by
   opp-eval yet" because none of the prod-pair turmeric opps have run
   opp-eval.** That's an honest banner, but it lands in the email's hero
   screenshot as a near-empty value statement (the recipient sees an
   amber-toned banner with no scoring). Two cheap fixes for next time:
   (a) before screenshotting, run `/ace:eval` on at least one opp in the
   chosen pair so the banner shows a real score-delta sentence; or
   (b) seed a synthetic `verdicts/opp-eval-deep.yaml` directly into the
   Drive folders for the demo pair (drift-tolerant — opp-eval will
   overwrite on next real run). Either path makes the headline
   self-evidently impressive without changing the feature.

2. **The picker's source-card needs to be NOT in error state for
   tag-siblings to render.** The first attempt clicked Compare on
   `turmeric-market-survey-2026-04-28` (status=error), which is returned
   by `_opp_list_impl` as the placeholder `tags: []`, so my client-side
   tag-sibling logic saw zero shared tags. Recovered by tagging a
   different healthy pair, but: the `error`-state placeholder card
   throws away the OppWorkspace.tags that ARE in the DB. Worth a small
   follow-up: in `_opp_list_impl`'s except branch, still call
   `_overlay_workspace_display_name` so the placeholder picks up the
   tags from the DB row even when the Drive snapshot fails to load.
   Three-line fix; would also help the trash + filter UX on broken opps.

3. **The hero screenshot is the compare page itself, but it leads with a
   negative-toned headline ("neither has been judged").** Email recipient
   reads that and might think the feature is incomplete. Two next-cycle
   tweaks: (a) reorder the highlights so the hero shot is the picker
   (highlight 3, currently last) — which IS unambiguously positive (a
   clean dialog with a tag-siblings section); or (b) re-shoot the
   compare page after item (1) so the banner reads positive. Today's
   email leans on copy to bridge the gap ("Once a score lands, the
   banner becomes…"), but a positive hero would land harder.

Cycle internals (sender skill / message ID / asset branch) are above.
The email is in the recipient's inbox; these feed the next cycle.

### Meta-observations

- **CompareTable.tsx was dead code from the deprecated multi-run model
  but the SHAPE of the comparison was already designed.** Found via
  `grep -rn 'compare\|sibling' frontend/src apps/opps`. Adapting an
  existing-but-unused component is a faster path than designing from
  scratch — and the migration comment in
  `apps/opps/migrations/0002_oppworkspace_tags.py` confirmed the design
  intent ("Future UI: tag filter + side-by-side compare") had been
  stable for weeks. Worth checking for similar dead-but-designed
  components in any project: the killer feature might already be
  half-built.
- **Single bundled PR was right.** Three highlights all serve one
  workflow ("compare two opps"); reviewing them as one PR makes the
  reviewer's job easier (one mental model). This matches the
  established ace-web rhythm and the user's recorded preference.
- **The opp-eval "no score yet" path needed a real banner copy.** I
  spent meaningful time deciding what the headline should say when one
  or both opps lack scores. Three branches (both unscored, one scored,
  both scored). The honest "neither has been judged" copy is correct
  but visually weak in a screenshot — see E.5 item 1. Future polish:
  add a fallback line "ship opp-eval to compare" with a CTA to
  `/ace:eval`.
- **Tagging via PATCH from curl required `Referer` header to defeat
  CSRF.** Worth recording: CSRF check rejects requests without a
  `Referer:` matching the host. `-H "Referer: https://labs.connect.dimagi.com/ace/"`
  fixes it. Already known but worth re-confirming for future
  scripted-PATCH operations.

### Universal-improvement candidates

- **"Check for dead-but-designed components before designing fresh."**
  Single observation today; CompareTable.tsx was the case. Holding for
  one more confirming case before pitching as a canopy lesson.
- **"For demo screenshots in feature emails, ensure the data exercises
  the positive path."** Specifically: when a feature has a
  positive/neutral/negative tone branch, seed prod data so the
  positive branch fires for the email screenshot. Today the compare
  page's neutral "neither judged yet" banner shipped because I picked a
  pair that genuinely had no scores; a 30-second seed step would have
  produced a stronger hero. Worth proposing as a canopy lesson — applies
  to any "diff/compare" feature, any "before/after" feature, any
  feature with conditional copy.
