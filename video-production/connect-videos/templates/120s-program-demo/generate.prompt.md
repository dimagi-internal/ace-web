# Generator skill: 120-second program demo

You are filling out a video spec for a single Connect by Dimagi
program at **demo depth** — the viewer already knows what Connect is
and now wants to see how the mechanism actually runs. You are given
this template's **example spec** — a complete, renderable `spec.yaml`
— and must produce a new `spec.yaml` of the **same structure**. Keep
the example's structure and brand scaffolding and replace only the
program-specific content per the guidance below. Each adapted field
is required.

**Important:** this template requires program-specific footage the
operator must hand-attach. The spec ships ready to render only after
that footage lands in the workspace's Drive folder. Until then the
output is for spec review only.

## What this video is for (and what makes it good)

This is a **120-second program demo**. The viewer is a funder who's
already seen the 60-second overview and is now scoping a real
engagement, OR a new Network Manager being trained on what
verification looks like end-to-end, OR a program manager presenting
at a partner kick-off.

The 60-second version is "Connect for stakeholders who don't know
Connect." This one is "*this specific program*, end-to-end, including
what nobody else in the room has seen yet — the verification +
audit-of-audits layer."

Three things make this version land:

1. **The verification subloop is the centerpiece.** The 60-second
   video can wave at verification ("evidence is checked"). The 120
   has to *show* it: GPS review, bulk image audit, the probation /
   relearn / deactivation lifecycle, the Audit-of-Audits dashboard.
   That's the most underseen part of Connect; this template's job
   is to bring it forward.
2. **The opening and closing rhyme.** Open on a drone shot of the
   village; close on the same drone return. The narration in between
   travels through the product. The structural symmetry tells the
   viewer "we came back to where we started; now you see what
   happens in between."
3. **It is concrete, not abstract.** Every beat names a real thing:
   a country, a partner, a stat, a screen, an action. The 120 has
   60% more runtime than the 60s — that runtime is for *specifics*,
   not for filler.

## Beat structure (Matt's MBW Killer Demo outline)

This template follows the 14-beat structure from the MBW Killer Demo
slide deck:

| Beat                | Target | What it does |
|---------------------|--------|------|
| `set_scene`         | ~15w   | Drone + village b-roll + lower-third. Place the viewer. |
| `problem`           | ~22w   | Stakes statistic. Reference the source page. |
| `connect_overview`  | ~20w   | 10-second recap: Learn / Deliver / Verify / Pay. |
| `learn`             | ~25w   | Animated slide-2 + FLW Learn screen recordings. What FLWs train on. |
| `learn_to_deliver`  | ~12w   | FLW passes test, receives credential, eligible for delivery. |
| `deliver`           | ~30w   | Animated slide-3 + FLW Delivery screen recordings. What FLWs do in the field. |
| `payment`           | ~15w   | Visit approved → payment notification on phone → amount earned. |
| `verification_intro`| ~14w   | "But how is service delivery verified?" — pivot to the backend. |
| `network_manager`   | ~25w   | NM oversees all FLWs. Verification rules + rejected payment example. |
| `audit_image`       | ~20w   | Bulk image audit. ANC cards. Objective criteria set during training. |
| `audit_gps`         | ~20w   | GPS table. Flagged behavior. Drill into a suspicious case detail. |
| `flw_lifecycle`     | ~25w   | Overview table. Followup-rate metric. Probation → deactivation. Relearn flow. |
| `program_manager`   | ~25w   | Audit-of-Audits dashboard. Dropoff-rate trend over time. |
| `closing`           | ~20w   | Drone return. "Verify delivery, pay results, enable donor insight." |
| `cta`               | 0w     | Empty. Outro brand card. |

Total: ~248 words at ~150wpm → ~99 seconds of narration. The
remaining ~20 seconds is breathing room: drone establishing time,
animation transitions, and the closing brand card.

## Narration voice (same anchors as 60s)

Documentary lower-third. Plain narrator. Numbers > adjectives.
Never use: "leverage", "synergy", "robust", "comprehensive",
"transformative", "game-changing", "world-class", "imagine if",
"what if we told you", "the future of", "a revolution in".

The narrator IS allowed to cite numbers, name countries, name
partner orgs, describe specific FLW actions, quote specific
dashboard metrics, and call out screen elements.

## Specific guidance per beat

- **`set_scene`** — must reference the country by name. Drone +
  village = place; don't waste words describing the drone shot.
  Lower-third does the country/program labeling.
- **`problem`** — pick the stakes stat the source page leads with.
  For MBW: EBF rates in Nigeria. For KMC: % of neonatal deaths
  post-discharge. Avoid Connect-level stats here — the program
  has its own.
- **`connect_overview`** — 10 seconds total. This is the *only*
  beat where the viewer is allowed to be reminded what Connect is.
  Don't rehash the 60-second hook here.
- **`learn`** — the FLW learning experience. Quote one specific
  module name from the program if available. Reference the
  certification step explicitly — that's the gating event.
- **`learn_to_deliver`** — the *transition* beat. Short by design.
  "FLW passes test, receives credential, notified eligible for
  Delivery."
- **`deliver`** — the most camera-rich beat in the spec. Each
  Delivery form is a concrete action. Quote one form name. Reference
  the photo + GPS evidence capture.
- **`payment`** — the moment of truth. "Visit approved. Payment
  notification on the phone. Worker can see exact amount earned."
- **`verification_intro`** — one rhetorical sentence flipping the
  viewer's attention from FLW phone → backend. "But how is service
  delivery actually verified?"
- **`network_manager`** — describe one concrete verification rule
  ("photo must show ANC card", "GPS must be within 50m of registered
  household") and one concrete rejected-payment example.
- **`audit_image`** — bulk image audit. Reference objective criteria
  set during onboarding with the LLO. Each picture judged against
  the same rubric.
- **`audit_gps`** — the GPS-flagged-suspicious-case story. Most
  vivid beat in the spec. Walk: GPS table → one flagged row → map
  drill-down → suspicious detail.
- **`flw_lifecycle`** — the corrective-action story. Probation →
  task sent → no response → deactivation. OR probation → improved
  → renewed. Followup-rate is the headline metric.
- **`program_manager`** — Audit-of-Audits. Longitudinal: trends of
  good→probation, probation→deactivated, dropoff rate over time.
  Frame as "the PM has higher oversight" — not "the PM looks at
  numbers."
- **`closing`** — return to the village. Three-part closing:
  "Connect verifies delivery, pays for results, enables donor
  insight."

## Footage requirements

This template REQUIRES program-specific footage. Emit a `manifest_todo:`
list (already scaffolded in the example) of every clip alias the
spec references. The operator hand-attaches before render. Until
attached, `manifest:` stays empty and the rendered output uses [TBD]
placeholder clips.

The minimum clip set per beat:
- `drone-village-open` / `drone-village-close` — drone bookends
- `scene-context-broll` — 2-3 short field clips for opening scene
- `slide-2-animated` / `slide-3-animated` — animated learn/deliver slides
- `flw-learn-screens` — 3-4 FLW Learn module screen recordings
- `flw-deliver-screens` — 4-6 FLW Delivery form screen recordings
- `payment-notification-screen` — visit-approved + payment-amount UI
- `nm-dashboard-walkthrough` — NM platform with verification rules
- `nm-image-audit` — bulk-image audit UI
- `nm-gps-review` — GPS table + map drill-down
- `nm-overview-table` — FLW overview with probation + followup-rate
- `pm-audit-of-audits` — PM dashboard with longitudinal trends

## Picking clips from the media library

The workspace has a curated **media library** at `videos/library/` in
Drive. Each video file there has a JSON sidecar with `name`, `tags`, and
an optional `description`. Items are referenced from `manifest:` using
the `library:video/<subfolder>/<filename>` syntax — stable across runs,
preferred over raw `gdrive:<id>.<ext>` IDs.

When the orchestrator injects `available_video_clips` into your prompt
context, each entry has this shape:

```yaml
- ref: "library:video/<subfolder>/<filename>"
  name: "<human label>"
  tags: ["<tag>", ...]
  description: "<optional>"
```

Before listing a clip alias in `manifest_todo:`, check
`available_video_clips`:

1. Identify what the slot is for (drone bookend / FLW screen / NM
   dashboard / etc. — see the minimum clip set above).
2. Look for a library item whose tags match the program's topic /
   country / app AND the slot's role.
3. If a fit exists, populate `manifest:` directly with its `ref`
   instead of leaving the alias in `manifest_todo:` for hand-attach.
4. If nothing fits, leave the alias in `manifest_todo:` for the
   operator to hand-attach.

The library refs are also MCP-callable any time via
`videos_list_library_video` if you need to refresh mid-generation.

**Tag conventions** (advisory, not enforced):

- **Topic/identity:** `uganda`, `kenya`, `kangaroo-care`,
  `midwifery`, …
- **Role:** `field-footage`, `app-screenshot`, `b-roll`,
  `establishing`, `drone`, `closeup`, `nm-dashboard`,
  `flw-learn`, `flw-deliver`, …

A scene-clip slot is looking for `field-footage` + the program's
country. A product-clip slot is looking for `app-screenshot` + the
program's app. Drone bookends look for `drone` + the program's
country.

**Audio is implicit.** The audio library grows when the renderer
synthesizes voiceover from your `narration_*` fields. Identical text +
voice config returns the same cached clip, so reusing exact strings
across programs reuses the audio.

## Output format

Output the **complete `spec.yaml`** — same shape as the example,
with the example's structure and brand scaffolding preserved. The
list below is the set of **fields to adapt** (every field is
required):

```
{
  "program_slug": str,
  "workspace_slug": str,
  "program_name": str,
  "country_focus": str,
  "status": str,
  "program_tagline": str,
  "program_url": str,
  "template_id": str,        # "120s-program-demo"
  "generated_at": str,       # ISO-8601 UTC at fill time
  "scene_lower_third": str,
  "problem_big": str,
  "problem_caption": str,
  "problem_source": str,
  "impact_1_big": str,
  "impact_1_caption": str,
  "impact_2_big": str,
  "impact_2_caption": str,
  "impact_3_big": str,
  "impact_3_caption": str,
  "narration_set_scene": str,
  "narration_problem": str,
  "narration_connect_overview": str,
  "narration_learn": str,
  "narration_learn_to_deliver": str,
  "narration_deliver": str,
  "narration_payment": str,
  "narration_verification_intro": str,
  "narration_network_manager": str,
  "narration_audit_image": str,
  "narration_audit_gps": str,
  "narration_flw_lifecycle": str,
  "narration_program_manager": str,
  "narration_closing": str,
  "narration_cta": str
}
```

Count words for each narration field. Trim before returning if any
beat exceeds its Max (Target ± 2). Audio runs over budget gets cut
mid-word at render time.
