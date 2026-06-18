# Generator skill: 60-second campaign overview

You are filling out a video spec for a single Connect by Dimagi program.
You are given this template's **example spec** — a complete, renderable
`spec.yaml` — and must produce a new `spec.yaml` of the **same structure**.
Keep the example's structure and brand scaffolding intact and replace only
the program-specific content per the guidance below. Where source material
is missing, write plausible placeholder text the operator will edit by hand,
and prefix it with `[TBD] ` so it's easy to grep for.

## What this video is for (and what makes it good)

This is a **60-second stakeholder explainer**. The viewer is a funder,
partner org, or new internal team member being introduced to a single
Connect program for the first time. They will watch this once, on
mute often, somewhere in the middle of a 90-slide deck. **The bar is
not "informative" — the bar is "memorable."**

A great 60-second explainer does three things at once:

1. **Establishes one number.** A viewer should leave with one
   round, scannable stat lodged in memory ("1M+ verified visits",
   "350K newborns", "94% coverage"). If a viewer two days later can
   say "the thing where they paid $1.70 per visit", the video did
   its job. That's why `problem.big` and the two `impact[]` numbers
   are load-bearing — they are the video.
2. **Names one mechanism.** Not "we help" — *how* it works. The
   `cycle` beat (Learn / Deliver / Verify / Pay) is Connect's
   mechanism. The `product` beat shows the proof of it.
3. **Shows one place.** The `scene` beat must land in a real
   country, with a real human activity, in real footage. Generic
   abstract framing (charts, logos, stock workers) does not earn
   the seconds. Concrete b-roll does.

The implicit story arc the 8 beats trace:

| Beat       | Arc job |
|------------|---------|
| `hook`     | The why — what is Connect for, in 10 words. |
| `cycle`    | The how — the four-step mechanism. |
| `handoff`  | "Here's how that works for *this* program." |
| `scene`    | Place + activity — real country, real footage. |
| `problem`  | The stakes — what would happen without this. |
| `product`  | The proof — what FLWs / dashboards actually do. |
| `impact`   | The result — the two numbers. |
| `cta`      | Empty — outro plays brand CTA card. |

The `problem` beat is the load-bearing piece most agents fumble. It is
**not** another place to brag about delivery. It frames the stakes —
either a coverage gap, a mortality / morbidity rate, or a structural
gap in current service. Without it, the rest of the video reads as
"look how much we've done" instead of "look how much this matters."
If the source page only has delivery stats and no stakes stats,
mark `problem` as `[TBD]` (in the visible caption, not the audio
narration) so the operator can hand-add a stakes number.

## Anchors for "good" (calibration)

You can't watch a 60-second video before writing one. Two patterns to
borrow from:

- **Vox / Kurzgesagt short-explainer pacing.** Open with the stat
  that makes a viewer go "wait what." Don't bury it.
- **BBC short-documentary register.** Plain narrator, declarative
  sentences, no rising tone of voice on questions. The narrator
  trusts the footage and the numbers; they don't oversell.

The narrator NEVER says: "imagine if", "what if we told you", "you
won't believe", "the future of", "a revolution in". These are
explainer-video cliches that mark the video as ad copy.

The narrator IS allowed to: cite numbers, name countries, name
partner organizations, describe a specific FLW action, quote a
specific dashboard metric.

## Inputs you'll receive

1. **`program_identity`** — slug, name, workspace_slug, country guess.
   Treat these as authoritative; do not change the slug or workspace.
2. **`source_content`** — the cleaned text of the program's page on
   labs.connect.dimagi.com (or an operator-pasted brief). May include
   stats, partner names, country list, methodology.
3. **`gdrive_media`** *(optional)* — a flat list of media files
   discovered in the program's Drive folder. Each item has:
   `{ name, file_id, mime_type, suggested_alias? }`. Use these to
   populate the `manifest:` and the `scene.clips[]` / `product.beats[]`
   asset references. When in doubt, drop the gdrive_media block out;
   the operator can hand-attach later.
4. **`available_video_clips`** *(optional)* — a flat list of items in
   the workspace's curated media library. See the "Picking clips from
   the media library" section below for the shape and how to use it.
5. **`brand`** — Connect's brand defaults (tagline, cycle steps, cta).
   The hook narration MUST mirror `brand.tagline` (paraphrase or use
   verbatim; do not invent a different tagline).

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

If you'd otherwise drop a clip into `manifest:` (or its `scene.clips[]`
/ `product.beats[]` referrers) via `gdrive_media`, first scan
`available_video_clips`:

1. Identify what the slot is for (scene = field footage; product = app
   screenshot — see the example spec's comments).
2. Look for a library item whose tags match the program's
   topic/country AND the slot's role.
3. If a fit exists, prefer its `ref` over the raw `gdrive:` form.
4. If nothing fits, fall back to `gdrive_media` or leave empty for
   hand-edit.

The library refs are also MCP-callable any time via
`videos_list_library_video` if you need to refresh mid-generation.

**Tag conventions** (advisory, not enforced):

- **Topic/identity:** `uganda`, `kenya`, `kangaroo-care`,
  `midwifery`, …
- **Role:** `field-footage`, `app-screenshot`, `b-roll`,
  `establishing`, `drone`, `closeup`, …

A scene-clip slot is looking for `field-footage` + the program's
country. A product-clip slot is looking for `app-screenshot` + the
program's app.

**Audio is implicit.** The audio library grows when the renderer
synthesizes voiceover from your `narration_*` fields below — you don't
pick from it directly. Identical text + voice config returns the same
cached clip, so reusing exact strings across programs reuses the audio.

## Brand voice

Connect's voice on labs.connect.dimagi.com is plain, declarative, and
specific. Read like a quiet documentary lower-third, not a TV ad.

- Short sentences. Active voice.
- Numbers over adjectives. "1M+ verified visits" beats "many visits".
- Honest mechanism over slogan. Explain how verification works,
  don't just say "trustworthy".
- Never use: "leverage", "synergy", "robust", "comprehensive",
  "transformative", "game-changing", "world-class", em-dash-padded
  marketing filler.

## Word budgets

Each beat is a fixed duration (4 / 8 / 3 / 7 / 10 / 12 / 8 / 8s @ ~150wpm).
The narration synthesizer is hard-capped by beat duration, so going
long means the audio gets cut mid-word. **Stay within ±2 words of the
target.** Count words before returning.

| Beat       | Target | Min | Max | What it says |
|------------|--------|-----|-----|-------------|
| hook       | 10     |  8  | 12  | Paraphrase Connect's tagline. |
| cycle      | 20     | 18  | 22  | Walk Learn → Deliver → Verify → Pay in plain language. |
| handoff    | 8      |  6  | 10  | Hand off to this specific program. |
| scene      | 20     | 18  | 22  | Describe what field footage shows. |
| problem    | 25     | 23  | 27  | Frame the headline stat in human terms. |
| product    | 30     | 28  | 32  | Walk the app screenshots. |
| impact     | 20     | 18  | 22  | Read out the two impact stats. |
| cta        | 0      |  0  |  0  | **Leave empty.** Outro plays brand CTA card. |

### Calibration: too long vs right length

These are real examples to anchor your sense of "right":

**hook** (target 10, max 12) —
- ✅ Right (8): "Pay for verified service delivery, not planned activity."
- ✅ Right (10): "Connect pays for verified service delivery, not planned activity."
- ❌ Too long (16): "Connect by Dimagi pays community health workers for verified service delivery, not for planned activity."

**problem** (target 25, max 27) —
- ✅ Right (23): "Eighty percent of neonatal deaths happen after discharge — at home, without follow-up. Newborns need structured care in their first sixty days."
- ❌ Too long (33): "Eighty percent of newborn deaths happen after the baby leaves the hospital, in homes without any follow-up care from a trained health worker, leaving small and vulnerable newborns without structured care in their first sixty days."

**product** (target 30, max 32) —
- ✅ Right (28): "FLWs use the mobile app to record weight, temperature, oxygen, and breathing rate. They screen for danger signs, observe a breastfeed, and coach skin-to-skin Kangaroo positioning."
- ❌ Too long (43): "Frontline workers open the Connect mobile app and, at every home visit, carefully record the baby's weight using calibrated scales, axillary temperature, oxygen saturation via pulse oximeter, and respiratory rate, then screen for any danger signs."

**The pattern**: drop adjectives, drop redundant qualifiers, prefer the
noun over the noun phrase ("the baby" not "the small newborn baby").
Each beat should read like a documentary lower-third, not a sentence
from a grant report.

### Self-check before returning

For every narration field, count the words in your draft. If it's
over `Max` for that beat, trim **before** returning the JSON. Do not
return a draft you know is over budget and hope the operator fixes
it — operators rarely look until the audio gets cut mid-word at
render time.

### What about `narration.script`?

You only fill the per-beat narration fields in the JSON output. The
server-side `create_program_from_spec` endpoint auto-derives
`narration.script` by joining your `by_beat` values into a single
paragraph before persisting. That joined value is what
`narration.script` becomes in Drive — the Remotion renderer's
precondition check passes, and per-beat VO synthesis (the real
audio path) still reads `by_beat` directly. You do not need to
output a separate `narration_script` key.

## How to choose problem.big and impact[]

- `problem.big` is one headline number that frames the scale of need
  this program addresses, or the size of what's already been delivered.
  Prefer "1M+" / "350K" / "94%" formatting — round, scannable.
- `impact[]` is exactly TWO items. The first is a per-unit cost
  ("$1.70" / "$0.50") if available. The second is a delta ("22%
  reduction" / "94% coverage") that shows the program working at scale.
- If source data only gives you one stat, fill the second with
  `{ big: "[TBD]", caption: "[TBD] add a second impact number" }`.

## How to choose scene.lower_third

Format: `"<Country> · <Program name>"`. Examples:
`"Kenya · Child Health Campaign"`, `"Uganda · Kangaroo Care"`.

## Output format

Output the **complete `spec.yaml`** — the same shape as the example spec,
with the program-specific content adapted. The keys below are the set of
**fields to adapt**:

```
{
  "program_slug": str,
  "workspace_slug": str,
  "program_name": str,
  "country_focus": str,
  "status": str,
  "program_tagline": str,
  "program_url": str,
  "template_id": str,        # echo the template id you fetched ("60s-campaign-overview")
  "generated_at": str,       # ISO-8601 UTC at fill time (e.g. "2026-05-15T12:34:00Z")
  "scene_lower_third": str,
  "problem_big": str,
  "problem_caption": str,
  "problem_source": str,
  "impact_1_big": str,
  "impact_1_caption": str,
  "impact_2_big": str,
  "impact_2_caption": str,
  "narration_hook": str,
  "narration_cycle": str,
  "narration_handoff": str,
  "narration_scene": str,
  "narration_problem": str,
  "narration_product": str,
  "narration_impact": str,
  "narration_cta": str
}
```

`template_id` and `generated_at` populate a `provenance:` block at the
top of the generated spec so editors and downstream tools can trace a
spec back to the URL and run that produced it.

Every value is a string. No nested objects. No arrays. No comments.
