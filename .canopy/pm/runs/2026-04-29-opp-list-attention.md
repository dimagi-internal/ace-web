## 2026-04-29 — opp-list-attention (autonomous)

Seventh cycle on ace-web; third autonomous run after first-chat-path (2026-04-28)
and session-previews (earlier today). Lens framing: user-value with focus on the
"I have many opps and can't tell which one needs me" pain point. Today the
opp list (`/opps`) shows status pills only; pending gates and judge scores live
inside the Workbench, one opp at a time. With 6+ sibling opps from tag-grouped
iterations, the cost of seeing "what needs me" is N clicks.

### Phase A — target email DRAFT (pre-implementation)

Theme: **See what needs your attention, without opening every opp.**

Three highlights, one bundled PR:

1. **A "Needs review (N)" pill at the top of /opps** counts opps with at least
   one pending gate; clicking it filters to that subset. Matching cards
   surface a small amber dot + the awaiting-skill name.

2. **Each opp card now shows its latest opp-eval score** — `82/100 ✓ pass`
   when an opp has a verdict, blank when it doesn't. The improvement loop
   becomes legible at a glance: tag-grouped sibling iterations of the same
   idea are visually comparable on one screen.

3. **Sort the opp list by status, score, or last activity** — new header
   control. Combined with the existing tag filter, "show me the highest-
   scoring run of this idea" stops being a per-opp click-through.

### Phase A self-critique

- **Clear:** PASS. Each highlight names a specific URL (`/opps`) and a
  specific UI element. Recipient knows what changed in 5s. Hero verb is
  "see what needs me" — concrete workflow win.
- **Testable:** PASS. Each "Try it" line is a real assertion: open /opps,
  observe pill / chip / sort. Backed by tests on the gate-count and
  verdict-read paths server-side.
- **Impressive:** PASS. This is the improvement loop made legible — the
  killer feature in `context.md` ("run → inspect → upgrade → rerun →
  compare") finally has a one-screen surface. Not polish; a workflow
  affordance the team will use weekly.

Approved. Proceeding to Phase B.

### Phase B — proposals

One bundled PR (`ace-web/auto/opp-list-attention`):

**Backend:**
- Extend `apps/opps/sync.py::load_opp_card` to compute pending-gate count
  + skill names from `state_data["gates"]` (already parsed; reuse
  `_gates_from_state`). Also: optionally read `verdicts/opp-eval-{deep,
  monitor,quick}.yaml` for the latest score + pass/fail. One extra Drive
  call per opp, bounded; skipped when `verdicts/` folder isn't listed in
  the opp's children.
- Update `apps/opps/views.py::_opp_list_impl` to surface the new fields
  on the card payload.

**Frontend:**
- `frontend/src/api/types.ts` — add `pending_gates: string[]`, `score:
  number | null`, `score_passed: boolean | null` to `OppCard`.
- `frontend/src/pages/OppListPage.tsx`:
  - "Needs review (N)" pill in header; click → filter to gate-pending
    cards. Persists alongside the existing tag filter.
  - Sort dropdown: `Recent activity` (default) / `Score (high → low)` /
    `Status` / `Slug`.
  - Per-card: amber gate dot + awaiting-skill text when pending; score
    chip (`82/100 ✓`) when verdict present.

**Tests:**
- `apps/opps/tests/test_load_opp_card.py` — gate-count + score-presence,
  verdict-folder-missing path, malformed-verdict graceful path.
- `apps/opps/tests/test_opp_list.py` — payload shape includes new fields.

### Phase C — ship outcome

**Branches + PRs:**
- Feature: `ace-web/auto/opp-list-attention` → PR #145, squashed to main as `9acd539`
- Fix-forward: `ace-web/auto/opp-list-attention-scale-fix` → PR #146, squashed to main as `a1e44fc`

**Why two PRs:** post-deploy verification on prod surfaced that the
score chip was hardcoded to `/100` but real opp-eval verdicts ride a
0-10 scale on at least one prod opp (`turmeric-market-survey-
2026-04-28` scored 8.2 → rendered as misleading "8/100"). Caught it
during the Phase E prod-screenshot pass and shipped a small fix-forward
matching `ScorecardPanel.tsx`'s existing `>10 ? /100 : /10` convention.
This was exactly the class of bug a real dogfood pass would have
caught earlier — file under "the prod-screenshot step IS the
dogfood pass for this kind of cycle."

**Convince-self gate:**

*3a. Mechanical:*
- pytest: 533/533 passing (up from 527 — 6 new opp-list tests)
- ruff: clean
- tsc -b: clean
- secret scan: clean
- diff size: 5 files, 447/-45 (≪ 1500 limit). Earlier the `npm install` from
  `testing.prepare` regenerated `frontend/package-lock.json` (the worktree
  didn't have a lock yet) — those 7k lines were unrelated to the feature
  diff and were unstaged before the gate.

*3b. Self-review (five questions):*

1. **What invariant did I just change?** The `/api/opps/` payload contract
   gained three additive fields: `pending_gates: string[]`,
   `eval_score: number | null`, `eval_passed: boolean | null`. The list
   view's Drive-call budget grew from `≤ 2N+1 list_files, ≤ N get_content`
   to `≤ (2+V)·N + 1 list_files, ≤ (1+V)·N get_content`, where V is the
   fraction of opps with a `verdicts/` folder. The
   `test_opp_list_drive_call_budget` test was updated to express the new
   contract; the asserted numbers for the existing fixture (no verdicts)
   are unchanged.
2. **What's the riskiest line?** `_load_opp_eval_summary` does
   `client.list_files(verdicts_folder.id)` + a `get_content` per opp that
   has been judged — adds O(0.7–1.5s) Drive latency per such opp on real
   Drive. Bounded by mature opps; not paid by new opps. Caching is
   future work.
3. **What would a senior eng object to?** "Why is this on the list
   endpoint at all? Lazy-fetch `/api/opps/scores` after paint to avoid
   blocking initial list render." Valid concern. Counter: the score chip
   has to render with the card or it'll cause a paint flash; the
   frontend wouldn't know which opps even have scores without first
   asking. The Drive cost is constant per judged opp and the slow path
   already costs O(N) on the existing endpoint.
4. **Tests codifying changed behavior?** Yes —
   `test_opp_list_drive_call_budget`. Updated the test's *intent*
   (docstring + budget formula) to express the new V-aware contract, not
   just the assertion numbers. Combined fixture has V=0 so the concrete
   bound is unchanged.
5. **Comfortable on vacation?** Yes. New fields default to safe values
   (`null` / `[]`); frontend uses `??` for absent fields; worst case is
   "score chip doesn't render", not data corruption.

*3c. Dogfood:* SKIPPED — local docker stack has a known port-6380 redis
collision in this emdash worktree (same as cycle 6, 2026-04-29-session-
previews). The change has comprehensive automated test coverage (6 new
tests across gate-pending, gate-mixed, score-deep-monitor-quick
preference, blank-opp, and malformed-verdict paths) plus a post-deploy
live probe planned for 3d.

*3d. Post-deploy health:* PASS for both deploys. `https://labs.connect.dimagi.com/ace/api/health` returned 200 on first poll for the feature merge AND the fix-forward merge. Live API verification confirmed the new payload fields are present and `pending_gates` is non-empty for 5 prod opps; `eval_score` is non-null for 1 prod opp (8.2/10).

### Phase D — reality reconciliation

What survived from the Phase A draft:
- "Needs review (N)" pill — shipped, demoable on prod (6 opps need review).
- Per-card amber gate dot + skill names — shipped, demoable on prod.
- opp-eval score chip — shipped, demoable on prod (`turmeric-market-survey-2026-04-28` shows 8.2/10 ✓).
- Sort dropdown (Recent activity / Score / Status / Slug) — shipped, demoable.

What changed from the draft: nothing structural. The fix-forward
adjusted the score chip's display format; everything else landed
as drafted.

Re-running Clear/Testable/Impressive: all PASS. The prod
screenshots show every claimed feature working on real data.

### Phase E — sent

- Sender skill: `ace:email-communicator`
- Sender account: `ace@dimagi-ai.com` (client `ace`)
- Recipient: `jjackson@dimagi.com`
- Subject: `[ace-web] What's new — see what needs your attention`
- Message ID: `19dda4504ff5bf73`
- Thread ID: `19dda4504ff5bf73`
- Asset branch: https://github.com/jjackson/ace-web/tree/pm-assets/2026-04-29-opp-list-attention
- Rendered HTML archive: https://github.com/jjackson/ace-web/blob/pm-assets/2026-04-29-opp-list-attention/email.html

### Phase E.5 — post-send self-review

Rendered the final `email.html` via headless Chromium at 1280×800
(desktop) and 375×812 (mobile). Saved as
`screenshots/email-rendered-{desktop,mobile}.png` and pushed to the
asset branch alongside the prod feature shots.

**Visual quality:**
- Linear/Stripe/Vercel grade rather than GitHub-issue. Brand bar fits
  cleanly at desktop and mobile (no two-line wrap on 375px because
  `ACE · RELEASE NOTES` is short — kept the lesson from
  2026-04-28-first-chat-path E.5).
- Three highlights, each with hero → body → image → caption → Try-it.
  Visual rhythm holds across the cycle.
- Soft border + subtle shadow on each screenshot read as figures, not
  pasted-in app shots. Lesson #11 captured cleanly.

**Communication clarity:**
- Headline lands the value in 5s ("See what needs your attention,
  without opening every opp."). The pitch (two sentences, within the
  first-chat-path cap) names the surface explicitly.
- Each highlight title states the user value
  (e.g. "A pill at the top counts opps awaiting review"), not the
  mechanism. Engineering specifics are confined to the soft footer.

**Technical correctness:**
- All three feature-shot URLs returned 200 before render.
- Title + image both wrap in `<a href="<TRY-IT-URL>">` per Hard rule #5.
- Score chip display matches `ScorecardPanel.tsx` convention now —
  caught and fixed via prod-screenshot recheck.

**Improvement ideas (ranked by impact):**

1. **The first highlight's screenshot is busy — recipient's eye has
   to find the new pill in the top header.** A red callout box around
   the "Needs review (6)" pill, or a tighter crop to the first row of
   cards + the header, would draw the eye to the new affordance
   instantly. The score chip on the second-row card is a nice visual
   surprise but it does compete with the highlight's stated subject
   (the pill).

2. **The third highlight's screenshot is a header strip cropped tight
   — only ~30px tall in the rendered email.** The sort dropdown is the
   visible feature but the strip is so narrow the eye barely reads
   "Sort by". Either crop wider (include the top row of cards too so
   the dropdown sits in context) or annotate the dropdown with a
   pointer.

3. **The score chip highlight could show before/after of the same
   opp.** Currently we describe the chip and show one card. A 2-up
   "before card (no chip)" / "after card (with chip)" would land the
   improvement viscerally. This is the kind of feature that *demands*
   a comparison shot.

4. **Sprint-internals footer paragraph has too many parenthetical
   asides.** "(#145 · feature, #146 · score-scale fix-forward caught
   from a prod recheck)" is dense; the parenthetical commentary turns
   what should be a procedural note into a story. Trim to "PRs #145 +
   #146" with the why elsewhere.

**Process improvements (canopy-PR candidates):**

- **Score chip and any other "render score from upstream verdict" UI
  should branch on scale, never assume scale.** Already a project
  precedent (ScorecardPanel.tsx); the new chip diverged. Worth a
  half-line addition to the cycle template's mechanical-checks: "When
  rendering numbers from upstream eval data, audit existing display
  conventions in the codebase." Possibly too narrow to be a universal
  canopy lesson; logging it here for now.

- **The prod-screenshot pass IS the dogfood pass for back-half
  cycles.** When 3c is skipped due to docker port collisions in a
  worktree, the Phase E prod-screenshot pass becomes the de facto
  verification step — and on this cycle it caught a real bug (the
  /100 hardcode). Consider promoting "render the new feature in prod
  before email" to a structural step rather than an artifact-of-the-
  email-process. Two cycles worth of evidence (this + 2026-04-29
  session-previews) before opening a canopy PR.

### Meta-observations

- **Three highlights, all demoable on prod, all impressive.** Best
  shape we've achieved on an autonomous cycle. The "needs review"
  pill counted 6 opps awaiting on prod the moment the cycle finished
  — that's a screenshot that tells a story. The score chip surfaced
  on a real opp (8.2/10) — also storytelling.
- **The fix-forward was the cycle's best signal.** The bug was real,
  the prod-screenshot caught it, the fix was 5 lines, the second
  deploy succeeded — the cycle's quality control did its job.
- **Drive-call budget update was the riskiest engineering call.** Did
  it carefully: kept zero-cost for unjudged opps, paid only for opps
  with an actual verdicts/ folder, updated the regression test's
  *intent* (V-aware contract) instead of just patching the assertion.
  Pattern to keep.
- **Bundled PR vs. one-feature-per-PR.** Bundled into one for the
  feature; needed a second small PR for the fix-forward. The bundled
  PR rhythm holds for thematically-coherent items; fix-forward is its
  own beast.

### Universal-improvement candidates

- **"Score / number rendering from upstream eval data should branch on
  scale, never hardcode."** Single observation; worth holding for one
  more confirming case before opening a canopy PR. The codebase
  already had the pattern (ScorecardPanel.tsx) — the regression was
  a fresh component diverging from it.
- **"The prod-screenshot pass IS the dogfood pass for back-half
  cycles."** Two cycles confirming (session-previews skipped 3c due
  to docker; this cycle skipped it for the same reason; both relied
  on prod-screenshot to verify). Worth a canopy lesson once a third
  cycle confirms.

### Phase D — reality reconciliation

(filled in during Phase D)

### Phase E.5 — post-send self-review

(filled in after send)
