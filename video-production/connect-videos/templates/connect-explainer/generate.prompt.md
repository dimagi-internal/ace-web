# Generator skill: how Connect works (generic explainer)

You are filling out a video spec for a generic ~42-second explainer
that answers one question: **how does Connect work?** You are given
this template's **example spec** (a complete, renderable `spec.yaml`)
and must produce a new `spec.yaml` of the **same structure** — keep
the example's beat structure and brand scaffolding, and replace only
the program-specific content per the guidance below.

This template runs in **explainer mode**: it deliberately OMITS the
problem + impact stat-card beats. Do NOT add a `problem:` or `impact:`
block — the example has none, and the renderer drops those beats from
the timeline when the fields are absent (see
`src/lib/spec.ts` — both are optional — and
`src/Root.tsx::filterDefaultsForSpec`). The rendered video is six
beats: hook, cycle, handoff, scene, product (four app clips), cta.

## What this video is for (and what makes it good)

The viewer has never seen Connect and wants the mechanism in one
breath: frontline workers **Learn** on their phone, **Deliver** guided
visits, every delivery is **Verified** (GPS + photo + an AI review
layer), and they are **Paid** automatically for verified work. Call out
Connect's AI features explicitly — the AI training coach during Learn,
and the AI-assisted verification review — because they are the
differentiator.

A great explainer:

1. **Is generic.** No prospect branding, no single program's stats or
   outcomes. Use a generic name (e.g. "Connect"). Keep
   Dimagi-branded chrome (tagline, the Learn/Deliver/Verify/Pay cycle,
   voice register).
2. **Shows the mechanism with real footage.** The scene beat uses field
   b-roll; the product beats are real app screencasts played as clips
   (`is_demo_clip: true`, no Ken Burns still-zoom).
3. **Names the AI features.** The product narration should mention the
   AI coach and the AI review layer, not just "training" and
   "verification."

## GROUNDING RULE

Never invent stats or organizational claims. This explainer carries no
numbers by design — keep it to how the loop works. If you find yourself
wanting to cite an outcome number, use `60s-campaign-overview` (which
has the stat-card beats) instead.

## Narration targets (per beat)

- `hook` (~10w): the last-mile delivery problem, in one line.
- `cycle` (~16w): name all four steps — Learn, Deliver, Verify, Pay.
- `handoff` (~8w): "here's how that works in the field."
- `scene` (~18w): what the field footage shows; the work becoming visible.
- `product` (~30w): walk the four app clips — AI coach in Learn, guided
  delivery, GPS + photo + AI review for Verify, automatic Pay.
- `cta`: leave empty — the outro plays under the brand CTA card.

## Library clips

This template references the standard workspace media-library clips via
`library:video/...` refs mapped through `manifest` `@alias` entries.
The eight clips available:

- field b-roll: `field-walking-towards-house.mp4`,
  `field-group-around-woman.mp4`, `field-walking-in-market-flws.mp4`
- mobile screencasts: `mobile-learn.mp4`, `mobile-mapping.mp4` (GPS),
  `mobile-pay.mp4`
- web screencasts: `web-microplan.mp4` (NM verification),
  `web-superset-graphs.mp4` (dashboard)

The example wires:

- scene.clips: `@field-walking-towards-house`, `@field-group-around-woman`
- product.beats (4): `@mobile-learn`, `@mobile-mapping`,
  `@web-microplan`, `@mobile-pay`

`web-superset-graphs.mp4` is **available but unused** in the v0 cut —
there are only four product slots (`product.beats` max 4) and two
scene slots are filled. If you want a dashboard moment, add it as a
third scene clip (`scene.clips` max 6) rather than dropping a product
beat. `field-walking-in-market-flws.mp4` is likewise a spare scene clip.

## Provenance

Set `template_id` to `connect-explainer` and `generated_at`
to an ISO-8601 UTC timestamp.
