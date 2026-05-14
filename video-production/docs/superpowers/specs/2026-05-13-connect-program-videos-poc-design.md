# Connect Program Videos — POC Design

**Date:** 2026-05-13
**Owner:** Jonathan Jackson (jjackson@dimagi.com)
**Status:** Design approved pending spec review.

## 1. Problem and goal

Dimagi's Connect public site at `labs.connect.dimagi.com` lists ten Connect programs (CHC, KMC, ECD, Reading Glasses, MBW, Chlorine Dispenser, Mental Health, Therapeutic Food, Survey & Data Collection, Rooftop Sampling). Today only the Child Health Campaign has a field documentary attached. We want a short (~60-second) video for *every* program, denser on product/UI content and quantitative impact than the current CHC doc, and we want producing a new one to take roughly an hour from data to MP4 — not days.

**Success criteria for the POC:**
1. A reproducible pipeline renders a 60-second MBW video from a single YAML spec and one CLI command.
2. The pipeline cleanly separates *infrastructure that's shared across all programs* (intro, outro, theme, narration template, render harness) from *per-program inputs* (footage, stats, copy).
3. Storyboard timing is data, not code — beats can be re-tuned per program or across the whole template without touching React components.
4. Adding the 11th program is a copy of one YAML file, a footage drop, and a render command. No code changes.
5. Output is web-ready (1080p H.264, burned-in captions, ≤30 MB) and looks consistent with the labs.connect.dimagi.com brand.

## 2. Audience and tone

Public-facing on `labs.connect.dimagi.com`. Two primary viewers:
- **Funders / philanthropists** evaluating where to invest — care about verified delivery, cost per outcome, scale numbers, fraud detection rigor.
- **Prospective LLOs** (local delivery organizations) considering applying — care about what the work looks like on the ground, how payment works, what platform support they get.

Internal sales is *not* a target audience for these short cuts; the existing CHC field doc and Matt's "killer demo" long-form script fill that role.

The reference for visual tone is the existing Connect by Dimagi CHC field documentary on `labs.connect.dimagi.com`. The 60-second cut compresses that style with heavier product UI inserts and motion-graphic stat cards, and lighter field b-roll.

## 3. Architecture

A standalone Remotion project lives at the repo root under `connect-videos/`.

```
connect-videos/
├── package.json              # remotion + @remotion/cli + @remotion/captions + react + ts
├── remotion.config.ts
├── tsconfig.json
├── src/
│   ├── Root.tsx              # registers compositions; reads YAML at composition time
│   ├── compositions/
│   │   ├── Intro.tsx         # 15s shared front-end (timeline-configurable beats)
│   │   ├── ProgramBody.tsx   # 37s body, fully props-driven from YAML
│   │   └── Outro.tsx         # 8s shared CTA + brand close
│   ├── components/           # StatCard, AppScreen, Lower3rd, KenBurns, CycleStep, Caption
│   ├── theme.ts              # colors / typography sourced from labs.connect.dimagi.com brand
│   └── lib/
│       ├── spec.ts           # YAML → typed ProgramSpec
│       ├── voiceover.ts      # ElevenLabs client, hash-keyed cache, writes WAV
│       └── narration.ts      # LLM-driven script generator (anthropic client)
├── programs/
│   ├── _defaults.yaml        # shared segment durations + overrides + voice config
│   ├── mbw.yaml              # one file per program
│   └── ...                   # one per program as we add them
├── assets/
│   ├── shared/               # cycle illustrations, logo SVG, reusable b-roll, music bed
│   ├── audio/                # generated VO files (cache, .gitignored)
│   └── programs/<slug>/      # per-program photos, screen recordings, field clips
├── scripts/
│   ├── render.ts             # `npm run render -- --program=mbw [--draft] [--preview-only]`
│   ├── narrate.ts            # `npm run narrate -- --program=mbw` (LLM draft → YAML)
│   ├── ingest-youtube.ts     # yt-dlp wrapper for grabbing reference footage / transcripts
│   └── brand-extract.ts      # one-time: pulls colors/SVGs from labs.connect.dimagi.com
└── out/                      # final MP4s (gitignored)
```

The Remotion app itself is just a React project; previewing during authoring is `npm start` (Remotion Studio in the browser). Rendering is `npm run render -- --program=<slug>`.

## 4. Storyboard model — timing as data

The 60-second video is a sequence of named beats. Each beat has a duration in seconds and a kind. The default beat set lives in `programs/_defaults.yaml`; any program may override per-beat duration or replace the beat list entirely.

```yaml
# programs/_defaults.yaml (excerpt)
fps: 30
total_seconds: 60
beats:
  - id: hook
    kind: intro_hook              # shared, drives <Intro/>
    seconds: 4
  - id: cycle
    kind: intro_cycle             # shared, animated Learn/Deliver/Verify/Pay
    seconds: 8
  - id: handoff
    kind: intro_handoff           # shared, "Here's how it works for {program}"
    seconds: 3
  - id: scene
    kind: body_scene              # per-program, hero clips with country lower-third
    seconds: 7
  - id: problem
    kind: body_problem_stat       # per-program, one big problem stat
    seconds: 10
  - id: product
    kind: body_product_beats      # per-program, 3 app/UI screens
    seconds: 12
  - id: impact
    kind: body_impact_stats       # per-program, 2 large impact numbers
    seconds: 8
  - id: cta
    kind: outro_cta               # shared
    seconds: 8
```

Per-program override (in `programs/mbw.yaml`):
```yaml
beat_overrides:
  scene: { seconds: 5 }            # less drone, more product
  product: { seconds: 14 }         # MBW has rich product story
```

`Root.tsx` resolves `_defaults.yaml` + program overrides at composition registration, computes start frames, and configures Remotion's `<Sequence/>` boundaries. Total must sum to `total_seconds`; the render script asserts and errors out otherwise.

This solves "I don't know until I see it" — adjusting timing is a YAML edit + re-render, no code change.

## 5. Per-program data spec (ProgramSpec)

```yaml
# programs/mbw.yaml
slug: mbw
name: Mother-Baby Wellness
country_focus: Nigeria
status: Piloting 2026
tagline: "Breastfeeding promotion and maternal mental health."

# Sources used by intro_handoff and outro_cta
program_url: https://labs.connect.dimagi.com/#/programs/mbw

# Beat content
scene:
  clips:
    - assets/programs/mbw/drone-village.mp4
    - assets/programs/mbw/mother-baby-01.jpg     # Ken Burns
    - assets/programs/mbw/flw-home-visit.mp4
  lower_third: "Nigeria · 2026 pilot"

problem:
  big: "29%"
  caption: "exclusive breastfeeding rate in Nigeria, under 6 months"
  source: "NDHS 2018"

product:
  beats:
    - asset: assets/programs/mbw/learn-cert.mp4
      caption: "FLW certified on EBF counseling"
    - asset: assets/programs/mbw/deliver-visit.mp4
      caption: "Home visit guided, GPS-stamped"
    - asset: assets/programs/mbw/payment-notif.mp4
      caption: "Paid on verification"

impact:
  - big: "$320K"
    caption: "GiveWell pilot grant"
  - big: "2,000"
    caption: "mother–baby pairs"

# Narration: either authored by hand here, or generated by scripts/narrate.ts
narration:
  generator: anthropic            # or 'manual'
  prompt_version: v1              # tracks template in src/lib/narration.ts
  script: |
    Across Nigeria, fewer than three in ten babies are exclusively
    breastfed in their first six months. Connect's Mother-Baby Wellness
    pilot is changing that, one home visit at a time…
    # filled by narrate.ts when generator=anthropic; editable by hand

# Voice render
voice:
  provider: elevenlabs
  voice_id: <stable_id>
  model: eleven_turbo_v2
```

`spec.ts` parses this into a typed `ProgramSpec` and validates required fields per beat kind (e.g., a `body_product_beats` beat must have at least 1, at most 4 product beats).

## 6. Narration pipeline (infrastructure, not one-off)

Three callable modes, all driven by the same `programs/<slug>.yaml`:

1. **Manual** — `narration.generator: manual`. The `script` field is hand-written. `narrate.ts` is a no-op for this program. Useful for hero programs that warrant copywriter polish.
2. **LLM-drafted** — `narration.generator: anthropic`. `npm run narrate -- --program=mbw` calls a prompt template in `src/lib/narration.ts` that takes the YAML data (problem stat, impact, product beats, audience, tone) and asks Claude to produce a ~150-word script timed to the beat durations. The result is written back into the YAML's `script` field for human review and edit before render.
3. **LLM-drafted + auto-render** — same as (2) but `render.ts` chains narrate → voice → video in one command when given `--auto`. For rapid iteration.

The prompt template encodes the Connect brand voice (verified, frontline-led, results-paid), the constraint that the narration must fit in the beat durations at ~150 words/minute, and the requirement that quantitative claims must be present in the YAML (no hallucinated stats).

`voiceover.ts` calls ElevenLabs with the script, caches output by `sha256(script + voice_id + model)` so identical scripts don't re-bill. Cached WAVs land in `assets/audio/<slug>-<hash>.wav` (gitignored).

## 7. Render pipeline

```
$ npm run render -- --program=mbw
```

Steps:
1. Load `programs/_defaults.yaml` + `programs/mbw.yaml`, merge with overrides, validate.
2. If `narration.script` is empty or stale (no matching audio hash), require explicit `npm run narrate` first — render fails loud rather than guess.
3. Synthesize VO via ElevenLabs (or skip if `voice.provider: none` for silent draft).
4. Compute per-beat start frames from beat durations and fps.
5. Generate VTT captions from the script aligned to VO duration via `@remotion/captions` whisper alignment (or estimated alignment if no whisper).
6. Invoke `remotion render src/Root.tsx ProgramVideo out/mbw-v<git-sha>.mp4` with `--props=<merged-spec.json>` and `--codec=h264 --crf=22`.
7. Burn captions on by default; `--no-captions` flag for a clean variant.

Useful render flags for iteration:
- `--draft` — 24fps, lower CRF, 720p, no VO regeneration. ~10s render.
- `--preview-only` — produces a single thumbnail per beat instead of a full render. ~2s. Lets you eyeball composition before paying for a render.
- `--from-beat=problem --to-beat=impact` — partial render of a beat range. Great for tuning a single section.

## 8. POC scope

**In POC (target: end-to-end working MBW render):**
- Remotion project scaffold (package.json, config, Root.tsx).
- Theme module: colors and typography extracted from labs.connect.dimagi.com (one-time scrape in `scripts/brand-extract.ts`).
- All three shared compositions: `<Intro/>`, `<Outro/>`, plus a stub `<ProgramBody/>`.
- `programs/_defaults.yaml` with the eight-beat default storyboard.
- `programs/mbw.yaml` populated from Matt's killer-demo script + labs.connect.dimagi.com MBW stats.
- `scripts/render.ts`, `scripts/narrate.ts`, `scripts/ingest-youtube.ts`.
- ElevenLabs VO integration (optional via env var; gracefully degrades to silent + caption-driven if no key set).
- `@remotion/captions` for burned-in captions.
- One full end-to-end render of `out/mbw-poc.mp4` using whatever raw assets the user supplies plus reference frames pulled from the existing MBW/CHC YouTube videos via `ingest-youtube.ts`.

**Deferred (post-POC, in priority order):**
1. The other 9 program YAMLs (no code change required, just data + assets).
2. Wistia upload automation (`scripts/upload-wistia.ts`).
3. Remotion Lambda cloud render config — useful once we're rendering >2 programs/day.
4. DaVinci Resolve color-grade pass for field b-roll (Stack B addition; placeholder hook in the pipeline).
5. Per-language VO variants (ElevenLabs supports many languages; trivial once template is locked).
6. A/B render diffing — render two beat-timing variants side-by-side for review.

## 9. Risks and open questions

- **Asset availability for MBW.** The pilot launches 2026 — meaningful field footage may not exist yet. POC falls back to photography (Ken Burns) and Connect platform screen recordings, which is acceptable and arguably more on-brand for the product-heavy direction.
- **Remotion company license.** Dimagi is over the per-seat free threshold. Assumed acceptable per the user; verify license cost at render time and document in `connect-videos/README.md`.
- **YouTube ingest for reference frames.** Using `yt-dlp` on our own uploads is legally fine; we should not embed yt-dlp'd third-party footage in published videos. The `ingest-youtube.ts` script is for reference and asset extraction from Dimagi's own uploads only; this is enforced by convention (and a comment), not by code.
- **Caption alignment without whisper.** If `@remotion/captions` whisper alignment is too heavy for the dev loop, fall back to estimated alignment (split by sentence, distribute across VO duration). Acceptable for POC, refine later.
- **Iteration on time split.** The user explicitly said they won't know the right balance until they see it. The beat-override mechanism in §4 is the answer; we should expect to tune `_defaults.yaml` once after the first 2–3 program renders.

## 10. Out of scope for the POC

- Multi-language UI (videos themselves may be re-narrated in other languages later; this design doesn't address site-side player UI).
- Interactive video / branching (Wistia supports it; not needed).
- Analytics instrumentation (handled by Wistia at the player level).
- A web UI for editing YAML specs (a future "Connect video author" app could be built on top; out of scope here).
