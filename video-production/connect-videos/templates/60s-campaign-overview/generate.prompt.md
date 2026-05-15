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
long means the audio gets cut mid-word. Stay within ±2 words.

| Beat       | Target words | What it says |
|------------|--------------|-------------|
| hook       | ~10          | Mirror Connect's tagline. |
| cycle      | ~20          | Walk Learn → Deliver → Verify → Pay in plain language. |
| handoff    | ~8           | "Here's how that works for {program_name}." |
| scene      | ~20          | Describe what field footage shows. |
| problem    | ~25          | Frame the headline stat in human terms. |
| product    | ~30          | Walk the app screenshots. |
| impact     | ~20          | Read out the two impact stats. |
| cta        | 0            | Leave empty. Outro plays brand CTA card. |

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

Every value is a string. No nested objects. No arrays. No comments.
