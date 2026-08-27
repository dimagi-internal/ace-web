# Generator skill: deliver on Connect — the LLO offer (generic)

You are filling out a video spec for a generic ~60-second **explainer**
aimed at a **local delivery organization (LLO)** — a locally led org that
recruits and manages frontline workers and is looking at **delivering**
programs on Connect. You are given this template's **example spec** (a
complete, renderable `spec.yaml`); produce a new `spec.yaml` of the **same
structure** — keep the example's beat structure and brand scaffolding and
replace only the program-specific content per the guidance below.

**TONE — explainer, not a pitch.** The audience already knows and likes
Connect (they've had a real intro call). Your job is to walk them calmly
through *how it works* for a delivery org: the loop, who does what, and how
verification and payment happen. Avoid persuasion ("no intervention pays as
much"), proof-point stat barrages, and marketplace pitch language. One
light scale fact for context is fine — lead with mechanism. Terminology and
plain facts can follow connect.dimagi.com; the *selling* should not.

This is the delivery-org POV; `program-designer` is the program-owner POV.
Keep it generic — no prospect name, no single LLO's outcomes. For a branded
prospect pitch use `partnership-pitch`; for a pure product-mechanism
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

## What to explain (and what makes a great cut)

Walk a delivery org calmly through how delivering on Connect works:

1. **The loop.** Every program runs the same loop — Learn, Deliver, Verify,
   Pay. Name it plainly.
2. **Who does what.** "You bring the frontline workers and the local
   relationships; Connect provides the app, the verification, and the
   payments." This is the "how the work is split" card.
3. **How verification works.** Each service is verified as it happens —
   biometric, GPS, photo — plus automatic data checks across visits. State
   it as the mechanism, not a brag.
4. **How payment works.** Once a service is verified, the worker is paid,
   directly to their phone.

One light scale fact (Connect already runs this way at scale) is fine for
context — don't stack a barrage of numbers.

## GROUNDING RULE

Use only **real facts** (terminology + plain numbers may follow
connect.dimagi.com), never invented ones — but keep them as *context*, not
a sell. Plain facts available: 1.5M+ verified services; 13 countries; 100+
frontline organizations; verification = biometric, GPS, photo, data audits;
payment goes to the worker's phone on verification. Skip the persuasion
lines ("no intervention pays as much", "no manual reviews, no delays, no
fraud") — they read as a pitch. Never attribute a program-specific outcome
to the LLO.

## Narration targets (calm explainer; per beat)

- `hook` (~12w): here's what it looks like to deliver a program on Connect.
- `cycle` (~12w): your teams run one loop — Learn, Deliver, Verify, and Pay.
- `handoff` (~8w): "here's how it works, step by step."
- `deal` → `narration.by_beat.ai_build` (~20w): you bring the frontline
  workers and local relationships; Connect provides the app, the
  verification, and the payments.
- `scene` (~16w): workers deliver in their own communities, and each visit
  is recorded as it happens.
- `traction` → `narration.by_beat.problem` (~16w): Connect already runs this
  way — over a million verified services, across thirteen countries.
- `product` (~28w): workers learn on their phones with an AI coach, deliver
  guided visits, and each service is verified — biometric, GPS, and photo,
  the moment it happens.
- `impact` (~12w): once a service is verified, the worker is paid — directly,
  to their phone.
- `cta`: leave empty — the outro plays under the brand CTA card.

## The "how the work is split" card (ai_build beat)

- `deal_headline`: short and plain — e.g. "How the work is split".
- `deal_term_1..4`: who does what, as chips (≤ ~5 words each): "You: workers
  + relationships", "Connect: the app & training", "Connect: verification",
  "Connect: payments".
- `deal_subhead`: one line, e.g. "You focus on delivery; Connect runs the
  rest."

## Scale-context stat (problem beat)

One calm fact, not a hard sell. `traction_big` ≤ ~6 chars (e.g. "1.5M+");
`traction_caption` (e.g. "verified services, across 13 countries");
`traction_source` (e.g. "connect.dimagi.com").

## Mechanism cards (impact beat — TWO cards, how it works)

Two cards that explain verification + payment (mechanism, not a sell). Keep
each `big` ≤ ~17 characters so it stays on one row at the StatCard auto-fit
size:

- `impact_big_1` / `impact_caption_1`: verification — "Verified" /
  "biometric, GPS, photo — as it happens".
- `impact_big_2` / `impact_caption_2`: payment — "Paid on proof" / "straight
  to the worker's phone".

## Library clips

This template references the standard workspace media-library clips via
`library:video/...` refs mapped through `manifest` `@alias` entries:

- scene.clips: `@field-walking-towards-house`, `@field-group-around-woman`
- product.beats (4): `@mobile-learn` (learn), `@mobile-mapping` (deliver),
  `@web-superset-graphs` (verify / data checks), `@mobile-pay` (pay)

There are only four product slots (`product.beats` max 4) — the
data-checks dashboard clip is deliberately one of them (it shows how
verification + auditing works). Caption it plainly ("Verify — and automatic
data checks"); don't drop it for b-roll.

## Provenance

Set `template_id` to `llo-deliver` and `generated_at` to an
ISO-8601 UTC timestamp.
