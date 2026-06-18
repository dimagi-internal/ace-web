# Generator skill: partnership pitch (prospect org)

You are filling out a video spec for a 90-second partnership pitch
aimed at a specific prospect organization that runs a real program
today but is not yet on Connect. You are given this template's
**example spec** — a complete, renderable `spec.yaml` — and must
produce a new `spec.yaml` of the **same structure**: keep the
example's beat structure and brand scaffolding, and replace only the
prospect/program-specific content per the guidance below. Fill every
field, even if source material is thin. Where source material is
missing, prefix the value with `[TBD] ` so it is easy to grep for.

**GROUNDING RULE (load-bearing — this goes to a prospect):** Never
invent stats, backstory, or organizational claims. Every number and
factual statement must trace to the research inputs you receive. If
a value lacks a traceable research source, write `[TBD] ` as a
prefix so a human reviewer can spot it before the video ships. Plausible-sounding
fabrications are worse than explicit `[TBD]` gaps for a prospect
audience. Keep Dimagi-branded chrome (tagline, cycle, voice register);
use the prospect's own name and their public logo only.

## What this video is for (and what makes it good)

This is a **90-second prospect pitch**. The viewer is a decision-maker
at an NGO or health ministry in active partnership discussions with
Dimagi. They may be in a meeting, or watching asynchronously before
a call. They already run a program — the question is whether Connect
is a credible upgrade path.

A great 90-second prospect pitch does three things at once:

1. **Mirrors their existing program.** The viewer should hear their
   own work described in the `handoff` beat — not generic health
   delivery, but the specific cadence or challenge that matches their
   program. This is why three narrative angles exist: pick the one
   that best maps to what the prospect's current program looks like.
2. **Shows the mechanism once, concretely.** The `cycle` beat walks
   Learn / Deliver / Verify / Pay. One of the `product` beats must
   be a real micro-demo clip (`is_demo_clip: true`) that shows the
   app in action — not a screenshot.
3. **Closes with numbers they can cite.** The `impact` beat ends on
   two concrete, research-grounded stats. These are the numbers the
   prospect will quote internally when making the case for Connect.

## Narrative angles

The spec carries three angles. Fill all three fully — the operator
picks one at render time via `active_angle`. Do not skip a beat;
write `[TBD] ` for any beat you cannot ground from research.

### `day-in-the-life`

Follows a single frontline worker (FLW) through one program cycle.
The hook names her role and place. The scene beat describes one real
visit. The problem beat names the gap she faces without a verification
system. Use this angle when the prospect's program has strong FLW
identity and field footage is available.

### `the-scale-gap`

Opens with the coverage gap — the distance between what the program
currently reaches and what the target population needs. The hook is
the gap stat. The cycle beat names Connect as the mechanism that
closes it. Use this angle when the prospect has published coverage
data and the gap is large enough to be arresting.

### `trust-travels`

Opens with how the prospect's program earns community trust today.
Positions Connect's verification layer as how that trust gets proven
to funders and replicated across geographies. Use this angle when
the prospect's competitive differentiator is their relationship with
communities, and they are expanding to a new country or funder.

## Inputs you'll receive

1. **`prospect_identity`** — slug, name, workspace_slug, country,
   sector. Treat slug and workspace as authoritative; do not change
   them.
2. **`prospect_yaml`** — the run's `prospect.yaml` file. This is the
   primary identity source: `name`, `region`, `sector`, `logo_asset`,
   `program_url`. Fill identity fields from this first.
3. **`angles_yaml`** — the run's `angles.yaml`. Contains three angle
   entries, each with an `angle_id` matching one of the three above
   and per-beat narration text grounded in the prospect research.
   **Use the text from `angles.yaml` verbatim for each angle's
   `by_beat` fields.** Do not rewrite angle narration; the research-
   grounding pass already ran. Your job is to map angles.yaml beats
   into the correct output keys.
4. **`source_content`** — cleaned text from the prospect's public
   site or research brief. Use this to fill `problem`, `impact`, and
   `scene` fields that are not covered by `angles.yaml`.
5. **`gdrive_media`** *(optional)* — flat list of media files from
   the prospect's Drive folder. Each item: `{ name, file_id,
   mime_type, suggested_alias? }`. Use to populate `manifest:` and
   `scene.clips[]` / `product.beats[]` asset references.
6. **`available_video_clips`** *(optional)* — curated workspace media
   library items. See "Picking clips" below. Prefer `library:` refs
   over raw `gdrive:` IDs for demo clips.
7. **`brand`** — Connect's brand defaults (tagline, cycle steps, cta).
   The `hook` narration in all three angles MUST mirror
   `brand.tagline` (paraphrase or verbatim; do not invent a different
   tagline).

## Setting `active_angle`

Set `active_angle` to the `angle_id` of the angle that best matches
the prospect's program character:

- Strong FLW identity + available field footage → `day-in-the-life`
- Large, documented coverage gap → `the-scale-gap`
- Community-trust differentiator + geographic expansion → `trust-travels`

If the research is thin or the choice is ambiguous, prefer
`the-scale-gap` as the default — the coverage-gap framing is the
most universally legible for a prospect audience.

## Setting `active_cut` and the `ai_build` card

`active_cut` selects whether the **ai_build** beat renders — a card that
says Connect's AI design tooling turns the prospect's existing protocol
into its Connect components. It doubles as proof the whole package was
AI-generated (a stated goal of the pitch).

- Default `active_cut` to `"ai"` — include the beat.
- Set `"standard"` only when the prospect is known to be AI-skeptical or
  the operator asks for a non-AI cut. The beat then drops; nothing else
  changes.

Fill the **shared** `ai_build` card (same across all three angles — it
describes the program's structure, which doesn't change with the angle):

- `ai_build_headline` (~12w): e.g. "AI turns <Prospect>'s protocol into a
  Connect program — in days, not months." Use the prospect's name.
- `ai_build_component_1..4`: the Connect components the program maps onto.
  Default: "Learn app", "Deliver app", "Verification rules", "Payment
  logic". Keep each ≤ ~3 words.
- `ai_build_subhead` (~8w): one line, e.g. "<Their program>, mapped onto
  Connect's rails."

Then write a **per-angle** `ai_build` narration line (the card is shared;
the framing differs by angle) — see the word-budget table. Ground it: the
AI builds from *their existing protocol*; do not claim AI invented their
program. For a greenfield-geography pitch, lean on "stood up in days" /
"a new country, fast" rather than implying an existing deployment.

## Picking clips from the media library

When `available_video_clips` is injected, scan for items whose tags
match the prospect's topic / country AND the slot's role:

- `scene.clips[]` → look for `field-footage` + the prospect's country
- `product.beats[]` → look for `app-screenshot` or `demo-clip` + the
  prospect's program topic. A beat with `is_demo_clip: true` MUST use
  a real walkthrough video clip (mp4/mov), not a still image.

Prefer `library:video/<subfolder>/<filename>` refs over raw `gdrive:`
IDs when a library match exists.

## Setting `is_demo_clip`

At least one `product.beats[]` entry must have `is_demo_clip: true`.
Set it to `true` when the asset is a real video walkthrough clip of
the Connect app — not a screenshot or annotated still. When `true`,
the renderer plays the clip as-is (no Ken Burns still-zoom). If no
real demo clip is available, write one beat as:
`{ asset: "[TBD] attach demo clip", caption: "[TBD]", is_demo_clip: true }`
so the operator knows to hand-attach before rendering.

## Brand voice

Plain, declarative, specific. Read like a quiet documentary
lower-third, not a TV ad.

- Short sentences. Active voice.
- Numbers over adjectives.
- Honest mechanism over slogan.
- Never use: "leverage", "synergy", "robust", "comprehensive",
  "transformative", "game-changing", "world-class", em-dash-padded
  marketing filler.
- Never say: "imagine if", "what if we told you", "you won't believe",
  "the future of", "a revolution in".

## Word budgets

Each beat is a fixed duration slot. Stay within ±2 words of the target.
Count words before returning.

| Beat    | Target | Min | Max | What it says |
|---------|--------|-----|-----|-------------|
| hook    | 10     |  8  | 12  | Paraphrase Connect's tagline. |
| cycle   | 20     | 18  | 22  | Walk Learn → Deliver → Verify → Pay. |
| handoff | 8      |  6  | 10  | Bridge to this specific prospect program. |
| ai_build| 16     | 14  | 18  | AI builds it from their protocol; fast. (AI cut only.) |
| scene   | 20     | 18  | 22  | Describe what field footage shows. |
| problem | 25     | 23  | 27  | Frame the headline stat in human terms. |
| product | 30     | 28  | 32  | Walk the app / demo clip. |
| impact  | 20     | 18  | 22  | Read out the two impact stats. |
| cta     | 0      |  0  |  0  | **Leave empty.** Outro plays brand CTA card. |

The narration synthesizer is hard-capped by beat duration. Going long
means the audio gets cut mid-word. **Self-check before returning:**
for every narration field, count the words in your draft. If it is
over `Max`, trim before returning the JSON.

## How to choose problem.big and impact[]

- `problem.big` is one headline number that frames the scale of need
  the prospect's program addresses. Prefer "1M+" / "350K" / "94%"
  formatting — round, scannable. Must come from research.
- `impact[]` is exactly TWO items. Prefer a per-unit cost metric
  first, then a coverage / outcome delta. If only one stat is
  available, fill the second with
  `{ big: "[TBD]", caption: "[TBD] add a second impact number" }`.

## How to choose scene.lower_third

Format: `"<Country> · <Prospect name>"`. Examples:
`"Kenya · Noora Health"`, `"Nigeria · Living Goods"`.

## Output format

Output the complete `spec.yaml` — the same shape as the example you
were given. The key list below is the set of **fields to adapt**:

```
{
  "prospect_slug": str,
  "workspace_slug": str,
  "prospect_name": str,
  "country_focus": str,
  "status": str,
  "tagline": str,
  "prospect_url": str,
  "template_id": str,          # echo "partnership-pitch"
  "generated_at": str,         # ISO-8601 UTC at fill time (e.g. "2026-06-01T09:00:00Z")
  "prospect_region": str,
  "prospect_sector": str,
  "prospect_logo_ref": str,
  "scene_lower_third": str,
  "problem_big": str,
  "problem_caption": str,
  "problem_source": str,
  "impact_1_big": str,
  "impact_1_caption": str,
  "impact_2_big": str,
  "impact_2_caption": str,
  "active_angle": str,
  "narration_day_in_the_life_hook": str,
  "narration_day_in_the_life_cycle": str,
  "narration_day_in_the_life_handoff": str,
  "narration_day_in_the_life_scene": str,
  "narration_day_in_the_life_problem": str,
  "narration_day_in_the_life_product": str,
  "narration_day_in_the_life_impact": str,
  "narration_the_scale_gap_hook": str,
  "narration_the_scale_gap_cycle": str,
  "narration_the_scale_gap_handoff": str,
  "narration_the_scale_gap_scene": str,
  "narration_the_scale_gap_problem": str,
  "narration_the_scale_gap_product": str,
  "narration_the_scale_gap_impact": str,
  "narration_trust_travels_hook": str,
  "narration_trust_travels_cycle": str,
  "narration_trust_travels_handoff": str,
  "narration_trust_travels_scene": str,
  "narration_trust_travels_problem": str,
  "narration_trust_travels_product": str,
  "narration_trust_travels_impact": str
}
```

`template_id` and `generated_at` populate the `provenance:` block at
the top of the generated spec so editors and downstream tools can
trace a spec back to the URL and run that produced it.

Every value is a string. No nested objects. No arrays. No comments.
The `cta` beats are left empty in the example and are NOT output keys.
