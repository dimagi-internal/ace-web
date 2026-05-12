# `phases.<phase>.products.*` contract — finish state-consolidation

**Date:** 2026-05-11
**Owner:** ACE
**Status:** Proposed
**Cross-cuts:** `ace` plugin (producer skills + manifest), `ace-web` (`apps/opps/summary.py`)

## Goal

Establish a single, crisp contract for the values every ACE phase makes
available to subsequent runs, downstream skills, and external readers
(notably ace-web's per-run summary page). Today's `outputs.<block>`
convention covers Connect, solicitation, selected LLO, and synthetic
(per state-consolidation PRs a–f, v0.13.163). This spec finishes the job:

1. Renames `outputs` → `products` for clarity.
2. Extends the block to phases 2, 4, 5, 8, 9 (the phases the
   consolidation sequence didn't reach).
3. Pins definitions so future skill authors know exactly which slot to
   write to.

After this lands, ace-web's `summary.py` reads `run_state.yaml`
top-to-bottom and never parses a markdown body for structured data
again.

## Definitions

> **`phases.<phase>.products.<block>`** — Pointers to things this phase
> brought into existence in the world. Most are entities in external
> systems (Connect program/opportunity, OCS chatbot, Labs solicitation,
> awarded LLO, generated synthetic workflows); some are durable
> ACE-produced artifacts that have a public-facing role (e.g. persona
> walkthrough decks, the training pack). Each value is **directly
> usable** — an ID you can pass to an API, a URL you can browse to, a
> date you can compare. Read this when you want to *use* what the phase
> produced.
>
> **`phases.<phase>.steps.<skill>.artifacts.<name>`** — Drive `fileId`s
> for the markdown / yaml / json files this skill wrote during this
> run. Per-run; the same skill on the next run will write different
> files with different fileIds. Read this when you want to *open* a
> file the skill produced.

Rule of thumb when deciding which slot to write a new field into:

- Can a consumer use this value without first fetching+parsing a file?
  → `products.*`
- Is the value a Drive `fileId`?
  → `artifacts.*` under the producing skill's `steps` entry.

## The rename: `outputs` → `products`

Mechanical:

- In the plugin: every skill `SKILL.md` write block, every agent doc
  reference, the state-consolidation spec, and the orchestrator's seed
  step (if/when it returns) update `outputs:` → `products:`.
- No backwards-compatibility fallback in ace-web — the plugin sweep
  ships first, then ace-web cuts over.
- Older run folders with `outputs:` keys are stale and not read.

## Per-phase punch list

Each section below names the canonical `products.<block>` shape, which
skill writes it, and the current state. Where a field is already
written today (as `outputs.<...>` post-consolidation, or as a scalar
under `steps.<skill>.*`), it's marked. Anything unmarked is a new
write the producer skill needs to add.

### `phases.design.products.pdd`

Producer: `skill:idea-to-pdd`

```yaml
phases:
  design:
    products:
      pdd:
        title: "Turmeric Market Survey"                       # NEW
        description: "FLWs visit markets to photograph..."    # NEW — one-paragraph overview
        file_id: <Drive fileId of 1-design/idea-to-pdd.md>    # already at steps.idea-to-pdd.artifacts.summary; promote
```

Today: `inputs/pdd.md` is parsed by ace-web for the hero name +
description. Both should be authored fields in state, not regex
extractions from a body.

### `phases.commcare-setup.products.apps`

Producers: `skill:pdd-to-learn-app`, `skill:pdd-to-deliver-app`, `skill:app-deploy`

```yaml
phases:
  commcare-setup:
    products:
      apps:
        learn:
          name: "Turmeric Market Survey — FLW Training"       # NEW (today in summary frontmatter)
          nova_app_id: mFknxMlsoLlkR28R2qpE                   # already at steps.pdd-to-learn-app.*
          nova_url: https://commcare.app/build/<nova_app_id>  # NEW — let the skill construct the right URL
          hq_app_id: d29dbb77012e400f9a700a731319ea55         # already at steps.app-deploy.*
          hq_url: https://www.commcarehq.org/a/.../apps/view/<hq_app_id>/  # already at steps.app-deploy.*
        deliver:
          name: ...
          nova_app_id: ...
          nova_url: ...
          hq_app_id: ...
          hq_url: ...
```

Today: ace-web has to reconstruct the Nova URL (the legacy
`/apps/<id>` URL stored in `2-commcare/pdd-to-{learn,deliver}-app_summary.md`
frontmatter is a 404; the working route is `/build/<id>`). Have
`skill:pdd-to-{learn,deliver}-app` write the **correct** URL into
`products.apps.<kind>.nova_url` so consumers don't have to know the
quirk.

### `phases.connect-setup.products.connect`

Producers: `skill:connect-program-setup`, `skill:connect-opp-setup`

Already formalized by PR a. Shape today:

```yaml
phases:
  connect-setup:
    products:
      connect:
        program:
          id: <UUID>
          url: ...
          labs_int_id: <int>
        opportunity:
          id: <UUID>
          url: ...
          start_date: 2026-06-14
          end_date: 2099-08-09
          name: "Turmeric Market Survey — turmeric (2026-05-03)"   # ADD if absent
        ace_test_user:
          invited_phone: ...
          invited_at: ...
```

`opportunity.name` is the only field worth confirming/adding — ace-web
displays it as the section title.

### `phases.ocs-setup.products.ocs_chatbot`

Producer: `skill:ocs-agent-setup` (writes the bot), with widget creds
augmented by `skill:ocs-widget-handoff`.

```yaml
phases:
  ocs-setup:
    products:
      ocs_chatbot:
        experiment_id: <UUID>           # NEW — today only at steps.ocs-agent-setup.*
        public_id: <id from widget-handoff.md table>            # NEW
        embed_key: <key from widget-handoff.md table>           # NEW
        admin_url: https://www.openchatstudio.com/a/connect-ace/chatbots/<experiment_id>/  # NEW
        team_slug: connect-ace          # so admin_url is self-contained for ace-web
```

Today: ace-web reads `4-ocs/ocs-setup_widget-handoff.md` (table parse)
and `4-ocs/ocs-agent-setup.md` (frontmatter parse) to assemble these
four fields. Have the writer skills land them as structured state
directly.

### `phases.qa-and-training.products.training`

Producers: 5 per-doc skills (`skill:training-llo-guide`,
`skill:training-flw-guide`, `skill:training-quick-reference`,
`skill:training-faq`, `skill:training-onboarding-email`) plus
`skill:training-deck-build` for the deck. Each skill writes its own
slot:

```yaml
phases:
  qa-and-training:
    products:
      training:
        deck:
          file_id: <Drive fileId — Slides>           # NEW — was discovered by mime-type listing
          title: "Turmeric Market Survey — Training Deck"
          web_view_link: https://docs.google.com/presentation/d/.../edit
        docs:
          llo_guide:
            file_id: <Drive fileId>
            title: "LLO manager guide"
            web_view_link: ...
          flw_guide:
            file_id: ...
            title: "FLW training guide"
            web_view_link: ...
          quick_reference:
            file_id: ...
            title: "Quick reference card"
            web_view_link: ...
          faq:
            file_id: ...
            title: "FAQ"
            web_view_link: ...
          onboarding_email:
            file_id: ...
            title: "Onboarding email"
            web_view_link: ...
```

Convention note: each doc skill writes its own
`products.training.docs.<key>.*` entry on completion via
`update_yaml_file` with two-level merge. The deck-build skill writes
`products.training.deck.*`. ace-web walks the dict in a fixed display
order regardless of which writers succeeded.

Today: ace-web lists `runs/<id>/5-qa-and-training/` and matches
filenames against a hardcoded title map (`_TRAINING_DOC_TITLES` in
`apps/opps/summary.py`). Authoring the human title in the skill that
writes the doc removes the mapping table.

### `phases.synthetic-data-and-workflows.products.synthetic`

Producers: `skill:synthetic-data-generate`, `skill:synthetic-workflow-seed`,
`skill:synthetic-workflow-polish`, `skill:synthetic-walkthrough-run`

Already formalized by PR d. ace-web wants in particular:

```yaml
phases:
  synthetic-data-and-workflows:
    products:
      synthetic:
        labs_opp_id: <int>
        workflows:
          llo_weekly_review_id: ...
          program_admin_audit_id: ...
        walkthroughs:
          - persona: llo-weekly-review
            run_id: 20260509-1430
            slideshow_file_id: <Drive fileId>      # ADD — today the HTML's location is by-convention only
            slideshow_url: https://drive.google.com/file/d/.../view
            eval_score: 8.4                        # OPTIONAL — surface in summary
          - persona: program-admin-audit
            ...
```

`walkthroughs[].slideshow_file_id` + `slideshow_url` is the only new
add — the rest is post-PR-d shape.

### `phases.solicitation-management.products.{solicitation, selected_llo}`

Producers: `skill:solicitation-create`, `skill:solicitation-review`

Already formalized by PR b. No new writes needed. ace-web reads:

```yaml
phases:
  solicitation-management:
    products:
      solicitation:
        solicitation_id: <UUID>
        labs_program_id: <UUID>
        deadline: 2026-06-15
        status: open | closed
        url: <public solicitation URL>             # CONFIRM present
      selected_llo:
        org_slug: <slug>
        org_display_name: "Acme Health Workers"    # ADD if absent
        contact_email: ...
        awarded_at: <ISO>                          # ADD if absent
```

### `phases.execution-management.products.launch`

Producer: `skill:llo-launch`

```yaml
phases:
  execution-management:
    products:
      launch:
        went_live_at: 2026-06-20T09:00:00Z         # NEW
        llo_org_slug: <slug>
        llo_org_display_name: "Acme Health Workers"
        first_visit_at: 2026-06-21T11:14:00Z       # OPTIONAL
```

Plus monitoring rollups, if the recurring-writer pattern lands later:

```yaml
      monitoring:
        last_qa_score: 7.8                         # from ocs-chatbot-eval-monitor
        last_qa_at: ...
        trend_file_id: <Drive fileId of 8-execution-manager/ocs-chatbot-eval_trend.md>
```

### `phases.closeout.products.{cycle_grade, opp_eval, learnings}`

Producers: `skill:cycle-grade`, `skill:opp-eval`, `skill:learnings-summary`

```yaml
phases:
  closeout:
    products:
      cycle_grade:
        letter: A | A- | B+ | ...                  # NEW
        headline: "Hit launch on schedule with zero blockers"  # NEW — one-line summary
        scorecard_file_id: <fileId of 9-closeout/cycle-grade.md>
      opp_eval:
        score: 82                                  # NEW — overall score
        verdict: pass | mixed | fail
        scorecard_file_id: <fileId>
        trend_file_id: <fileId>
      learnings:
        summary_file_id: <fileId>
        new_pdd_file_id: <fileId>                  # if iteration mints a follow-up
```

Today: ace-web detects `9-closeout/cycle-grade.md` existence for the
status flip to `closed`, but doesn't display the grade letter or
opp-eval score. Once `products.closeout.*` lands, the summary's hero
chip shows the actual grade, not just "closed."

## ace-web `summary.py` after this contract lands

Pseudocode of the rewrite:

```python
def build_summary_payload(drive, *, workspace, opp_slug, run_id):
    opp_yaml = read_yaml(drive, f"ACE/{opp_slug}/opp.yaml")
    state    = read_yaml(drive, f"ACE/{opp_slug}/runs/{run_id}/run_state.yaml")

    return {
        "opp": {
            "workspace_slug": workspace.slug,
            "slug": opp_slug,
            "run_id": run_id,
            "display_name": (
                state["phases"]["design"]["products"]["pdd"]["title"]
                or opp_yaml.get("display_name")
                or opp_slug
            ),
            "description": state["phases"]["design"]["products"]["pdd"]["description"],
            "status": _status_from(state),       # reads closeout.products.cycle_grade presence
            "end_date": state["phases"]["connect-setup"]["products"]["connect"]["opportunity"]["end_date"],
        },
        "apps":           _apps(state),
        "connect":        _connect(state, opp_yaml),   # program from opp.yaml, opportunity from state
        "training":       _training(state),
        "assistant":      _assistant(state),           # ocs_chatbot block
        "walkthroughs":   _walkthroughs(state),        # NEW section, Phase 6
        "solicitation":   _solicitation(state),       # NEW, Phase 7
        "selected_llo":   _selected_llo(state),        # NEW, Phase 7
        "launch":         _launch(state),              # NEW, Phase 8
        "monitoring":     _monitoring(state),          # NEW, Phase 8
        "cycle_grade":    _cycle_grade(state),         # NEW, Phase 9
        "opp_eval":       _opp_eval(state),            # NEW, Phase 9
        "learnings":      _learnings(state),           # NEW, Phase 9
        "open_questions": _open_questions(state),
        "workbench_url":  f"/w/{workspace.slug}/opps/{opp_slug}/runs/{run_id}",
    }
```

Roughly: 700 lines of regex / table / frontmatter parsing → ~150 lines
of dict-walking with `dict.get` chains. Every new phase covered for
free.

## Out of scope

- **OCS chatbot cross-run reuse** (`opp.yaml.ocs_chatbot.experiment_id`).
  The state-consolidation spec deliberately deferred this; once it
  lands, the chatbot can be reused across runs in the same shape we
  reuse the Connect program. ace-web's summary already works fine
  without it (each run has its own widget creds today).
- **Recurring writers (monitor skills).** Deferred per PR f's revert;
  the `products.execution-management.monitoring` block ships when the
  recurring-writer pattern is re-introduced.
- **Migrating already-running opps.** No backfill. Old runs render
  whatever ace-web's defensive `dict.get` returns (mostly empty
  sections). New runs after the plugin sweep render fully.

## PR sequencing

Suggested:

1. **Plugin: rename + Phase 2** — `outputs` → `products` across all
   existing writers (connect, solicitation, synthetic), plus add
   `phases.commcare-setup.products.apps` to `skill:pdd-to-learn-app`,
   `skill:pdd-to-deliver-app`, `skill:app-deploy`.
2. **Plugin: Phase 1 + Phase 4** — `products.pdd` and
   `products.ocs_chatbot`.
3. **Plugin: Phase 5** — `products.training.{deck, docs}` across the
   six writer skills.
4. **Plugin: Phase 9** — `products.{cycle_grade, opp_eval, learnings}`.
5. **Plugin: Phase 8** — `products.launch`.
6. **ace-web: `summary.py` rewrite** — read everything from
   `run_state.yaml`, drop the markdown body parsing helpers.
7. **ace-web: summary page UI** — add the new sections (walkthroughs,
   selected LLO, launch, cycle grade) the rewrite now has data for.

Steps 1–5 are independent in the plugin and can land in any order.
Step 6 can land partially as each plugin slice lands (the dict-walk is
defensive). Step 7 follows step 6 once the data is consistently
present.
