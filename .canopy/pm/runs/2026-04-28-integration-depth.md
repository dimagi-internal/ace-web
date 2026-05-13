## 2026-04-28 — integration-depth

Third cycle of the day. Lens framing: the Workbench is supposed to be a hub the user inspects an opp from. Each reachable canonical thing in the ecosystem (Drive file, CommCare HQ app, nova app, OCS chatbot, GitHub PR) that requires copy-paste instead of one click is a depth gap.

### Do it

1. **Auto-link http(s) URLs in artifact frontmatter** — Effort: S — Status: shipped
   - Branch: `ace-web/pm-scout-integration-depth`
   - What: `frontend/src/components/opps/ArtifactBody.tsx` was rendering every frontmatter key/value in a dl/dt/dd table as plain text. Now any value matching `^https?://\S+$` renders as an `<a target=_blank>` with an external-link icon.
   - Outcome: real conventions from the ace plugin (nova_app_url, learn_app_url, deliver_app_url, hq_base_url) jump to the connected tool with one click. Non-URL values (slugs, IDs, ISO timestamps) render as plain text as before.

2. **Active-artifact header shows Open in Drive** — Effort: S — Status: shipped
   - What: The artifact list at `StepDetailPane.tsx:110-120` already had a per-artifact Drive link icon. The focused-artifact header at `:127-141` was bare. Added a matching `Open in Drive ↗` link to the focused header so the canonical Drive file is always one click away while reading.
   - Outcome: focused-artifact header strip now has a right-aligned "Open in Drive" link.

3. **Chat seeds include a Workbench deep-link** — Effort: S — Status: shipped
   - What: `build_chat_seed` (apps/opps/seed.py) gains optional `workbench_url`. The `discuss` view (apps/opps/views.py:562) builds the URL from `request.build_absolute_uri()` + workspace slug + opp slug + run id + skill, and passes it through. Seed message now includes "View in Workbench: ..." near the top.
   - Outcome: a user reopening a Discuss-in-chat session days after seeding it has a one-click path back to the originating step page.

### Backlog

1. **LinkedChats preview snippet** — Effort: M — Why not now: borderline polish; current title + owner is functional. Revisit if a user mentions trouble scanning long lists.

### Closed
(none)

### Meta-observations

- **Three small wins again, one bundled PR.** The pattern from the previous two cycles holds — small, thematically-coherent items ship cleanly together. Three cycles in, this feels like the natural rhythm for ace-web polish work.
- **Real conventions from the sibling repo informed the proposal quality.** Reading `../ace/skills/*/SKILL.md` to discover that `nova_app_url`, `learn_app_url`, etc. are real frontmatter keys (not hypothetical) made the URL-auto-linking proposal much sharper. Worth doing this kind of cross-repo reconnaissance for any integration-depth scout — the surface I'm trying to integrate WITH lives somewhere else.
- **Same UI verification ceiling** as prior cycles. Type check + targeted tests are the bar; can't easily exercise the full "open an opp with deployed apps and see the URLs become links" without a populated test fixture or live data.
- **Workbench URL plumbing is now precedent.** The `request.build_absolute_uri('/w/<slug>/...')` pattern in the discuss view is reusable for any future feature that needs to surface a "back to ace-web" link in a chat seed, email, or share token.

### Universal-improvement candidates

- **"Read the sibling-repo conventions before proposing integration-depth fixes."** Single observation, but it had real impact on proposal quality. Holding for now to see if it recurs.
