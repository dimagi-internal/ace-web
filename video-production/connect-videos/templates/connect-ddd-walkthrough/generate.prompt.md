# Generator skill: walkthrough explainer (connect-ddd-walkthrough)

You are turning an **existing product walkthrough recording** plus a
short list of per-section sentences into a video spec. You are given this
template's **example spec** — a complete, renderable `spec.yaml` — and
must produce a new `spec.yaml` of the **same structure**: keep the
example's structure and replace only the content (title, walkthrough
sections, lower-third labels, per-section narration) per the guidance
below. This is NOT the marketing
arc — there is no hook, cycle ring, stat card, or tagline paraphrase.
The recording is the product; your narration points at the right thing
at the right moment.

## What this video is

- **One title card** (`intro_title`) — the topic, in a few words.
- **N walkthrough sections** (`body_walkthrough`) — each plays a RANGE
  of the ONE master recording full-bleed, with a short lower-third
  label and one spoken sentence.
- **One end card** (`outro_card`) — the brand outro.

A great explainer section does exactly one thing: it names what the
viewer is looking at and the single conclusion to draw from it. No
recap, no hype, no second clause that introduces a new idea.

## Inputs you'll receive

1. **`program_identity`** — slug, name, workspace, country. Authoritative.
2. **`master_recording`** — a ref to the ONE screen recording every
   section slices into (`file:`/`gdrive:`/`library:` form). Put it in
   `manifest.master`; every `walkthrough.sN.asset` is `"@master"`.
3. **`sections`** — an ordered list. Each item is:
   `{ start_seconds, end_seconds, lower_third, sentence }` where
   `start_seconds`/`end_seconds` are seconds INTO the master recording,
   `lower_third` is the on-screen label, and `sentence` is the VO.

## How to fill the spec

For each section `sN` (in order, ids `s1`, `s2`, … — add or remove
`sN` blocks in both `beats:` and `walkthrough:` to match the count):

- `walkthrough.sN.start_seconds` = the section's `start_seconds`.
- `walkthrough.sN.duration_seconds` = `end_seconds - start_seconds`.
- `beats[sN].seconds` = the SAME `end_seconds - start_seconds` (the
  on-screen duration must equal the clip range).
- `walkthrough.sN.lower_third` = the section's `lower_third` (keep it
  short — it sits above the caption).
- `narration_sN` = the section's `sentence`, verbatim or lightly tightened.

`intro_title` is fixed at 4s and `outro_card` at 5s — leave them.

## Lower-third vs sentence

- **lower_third** is a label — a noun phrase a viewer reads at a glance
  ("The per-surveyor quality scorecard"). No period, no verb required.
- **sentence** is the voiceover — one declarative sentence that states
  the conclusion ("Quality is computed per surveyor … so one
  under-performing surveyor is visible rather than averaged away.").

## Narrator voice

Plain, declarative, documentary. Same rules as the campaign template:

- Short sentences, active voice, numbers over adjectives.
- The narrator trusts the footage. No "imagine if", "what if", "you
  won't believe", "the future of", "revolution".
- Never: "leverage", "synergy", "robust", "comprehensive",
  "transformative", "game-changing", "world-class".
- One idea per section. If a sentence has two clauses introducing two
  ideas, split it into two sections (and two clip ranges).

## Word budget

A section's spoken sentence must fit its clip range at ~150 wpm
(≈ 2.5 words/second). For a 12-second section, stay under ~30 words.
The renderer audio-aligns (extends a beat whose VO overruns) but a
sentence that's wildly over budget makes the pacing drag. Count words
before returning; trim to the conclusion.

## `narration.script`

You only fill the per-beat `narration_sN` fields (and
`narration_title`). The server-side `create_program_from_spec` endpoint
joins the `by_beat` values into `narration.script` before persisting —
you do not output a separate script blob.

## Output format

Output the complete `spec.yaml` — the same shape as the example. The
keys below are the set of **fields to adapt**:

```
{
  "program_slug": str,
  "workspace_slug": str,
  "program_name": str,
  "country_focus": str,
  "status": str,
  "program_tagline": str,
  "program_url": str,
  "template_id": "connect-ddd-walkthrough",
  "generated_at": str,            # ISO-8601 UTC
  "master_asset": str,            # file:/gdrive:/library: ref
  "narration_title": str,
  "sections": [                   # one per walkthrough section, in order
    {
      "start_seconds": number,
      "seconds": number,          # = end_seconds - start_seconds
      "lower_third": str,
      "sentence": str
    }
  ]
}
```

The operator's tooling expands `sections[]` into the `s1..sN` blocks
(both `beats:` and `walkthrough:`) and the matching `narration_sN`
keys. Keep `sections` ordered; ids are assigned positionally.
