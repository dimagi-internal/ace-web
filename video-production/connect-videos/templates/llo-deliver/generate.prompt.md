# Generator skill: deliver on Connect — the LLO offer (generic)

You are filling out a video spec for a generic ~67-second explainer aimed
at a **local delivery organization (LLO)** — a locally led org that
recruits and manages frontline workers and is deciding whether to
**deliver** programs on CommCare Connect. The output is a JSON object
whose keys map to `{{placeholders}}` in `spec.template.yaml`. Fill every
placeholder.

This is the **other side of the marketplace** from `program-designer`.
That template answers "bring *your program* onto Connect"; this one
answers, from the delivery org's seat, **"what does it look like to
deliver on Connect, and why would I want to?"** The source of truth for
the messaging is Connect's LLO-facing overview (the marketplace deal,
real platform traction, fair auditing, and a trial-run on-ramp).

Keep it generic — no prospect name, no single LLO's outcomes. For a
branded prospect pitch use `partnership-pitch`; for a product-mechanism
explainer use `connect-explainer`.

## The two cuts (one spec)

This template renders from `active_cut`:

- `active_cut: ai` — includes the **deal** beat (a card naming the terms
  of the offer). ~67s, 9 beats. **Default to this** — the deal is core to
  the LLO pitch.
- `active_cut: standard` — drops the deal card; everything else identical.
  ~60s, 8 beats.

The deal card renders through the `ai_build` beat (the card is
content-generic: headline + chips + subhead). Author the `ai_build` block
and `narration.by_beat.ai_build` line regardless — they're just unused in
the standard cut.

## What an LLO cares about (and what makes a great cut)

Lead with the things a delivery org actually weighs:

1. **The deal.** Do I get paid, for what, and when? The deal card names
   it: a pay-per-service contract, no infrastructure to build, paid on
   verification, and a small trial run to start. This is the single most
   important beat.
2. **Proof it's real.** An LLO won't join a pilot promise. The hero
   traction stat (problem beat) and the traction cards (impact beat) put
   real Connect numbers on screen.
3. **How I'm managed — and that it's fair.** The product loop includes an
   *audited* beat: delivery is verified and audited automatically, and
   honest work is protected (fraud detection flags bad actors, not honest
   ones). Frame auditing as protection, not surveillance.
4. **How to start small.** The trial-run chip + narration make the
   on-ramp explicit.

## GROUNDING RULE

This template DOES carry real platform numbers — but only **cited Connect
facts**, never invented ones. Safe, grounded figures to draw from:

- 1.5M+ verified services delivered; 13 countries; 10× year-on-year.
- 200+ local delivery organizations (LLOs); 250k+ verified visits/month.
- Signed MoUs with Ministries of Health (DRC, Sierra Leone, Liberia,
  Uganda, Kenya).
- ~$1.30 average paid per verified visit (CHC Nigeria pilot).
- 94% population coverage with microplanning (vs 84% without).
- 0.91 AUC fraud-detection model (adversarial test).

If you don't have a real figure for a slot, use a value prop, not a made-up
number. Never attribute a program-specific outcome to the LLO.

## Narration targets (per beat)

- `hook` (~14w): you know your community; Connect turns local delivery into
  paid, verified work at real scale.
- `cycle` (~14w): name all four steps — Learn, Deliver, Verify, Pay — as
  the loop your teams run.
- `handoff` (~8w): "here's what delivering on Connect looks like."
- `deal` → `narration.by_beat.ai_build` (~24w): Dimagi contracts your org
  to deliver and pays per verified service; you recruit and train workers,
  Connect verifies and pays; start with a trial run.
- `scene` (~18w): field footage — workers reaching people, every visit
  verified the moment it happens.
- `traction` → `narration.by_beat.problem` (~18w): proof it's real — over
  a million verified services, across many countries; not a pilot.
- `product` (~30w): walk the four clips — train with an AI coach, deliver
  guided visits, audited fairly (honest work protected), paid per verified
  visit.
- `impact` (~18w): you're in good company (200+ LLOs), paid per verified
  visit, with tools that help you reach more.
- `cta`: leave empty — the outro plays under the brand CTA card.

## The deal card (ai_build beat)

- `deal_headline`: one line, e.g. "Dimagi contracts you to deliver — paid
  per verified service."
- `deal_term_1..4`: the terms as chips, ≤ ~4 words each. Default:
  "Pay-per-service contract", "No infrastructure to build", "Paid on
  verification", "Start with a trial run".
- `deal_subhead`: one line, e.g. "Connect handles matching, verification,
  and payment — you focus on delivery."

## Hero traction stat (problem beat)

- `traction_big` ≤ ~6 chars (e.g. "1.5M"); `traction_caption` (what it
  counts, e.g. "verified services across 13 countries"); `traction_source`
  (citation, e.g. "CommCare Connect, 2026").

## Traction cards (impact beat — 3 cards, REAL numbers)

Keep each `big` ≤ ~17 characters so it stays on one row at the StatCard
auto-fit size. Default trio:

- `impact_big_1` / `impact_caption_1`: good company — "200+" / "local
  organizations delivering on Connect".
- `impact_big_2` / `impact_caption_2`: pay — "$1.30" / "average paid per
  verified visit".
- `impact_big_3` / `impact_caption_3`: reach — "94%" / "coverage reached
  with microplanning".

## Library clips

This template references the standard workspace media-library clips via
`library:video/...` refs mapped through `manifest` `@alias` entries:

- scene.clips: `@field-walking-towards-house`, `@field-group-around-woman`
- product.beats (4): `@mobile-learn` (train), `@mobile-mapping` (deliver +
  GPS), `@web-superset-graphs` (audit dashboard), `@mobile-pay` (pay)

There are only four product slots (`product.beats` max 4) — the audit
dashboard clip is deliberately one of them, because "managed and audited
fairly" is a core LLO concern. Don't drop it for b-roll.

## Provenance

Fill `{{template_id}}` with `llo-deliver` and `{{generated_at}}` with an
ISO-8601 UTC timestamp.
