# Generator skill: 60-second campaign overview

You are filling out a video spec for a single Connect by Dimagi program.
The output is a JSON object whose keys map to placeholders in
`spec.template.yaml`. Each key is required — fill every one, even if
the source material is thin. Where source material is missing, write
plausible placeholder text the operator will edit by hand, and prefix
it with `[TBD] ` so it's easy to grep for.

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
4. **`brand`** — Connect's brand defaults (tagline, cycle steps, cta).
   The hook narration MUST mirror `brand.tagline` (paraphrase or use
   verbatim; do not invent a different tagline).

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

Return ONLY a single JSON object — no prose, no markdown fences. Keys:

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
