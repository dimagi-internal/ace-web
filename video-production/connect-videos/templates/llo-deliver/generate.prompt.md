# Generator skill: deliver on Connect — the LLO offer (generic)

You are filling out a video spec for a generic ~67-second explainer aimed
at a **local delivery organization (LLO)** — a locally led org that
recruits and manages frontline workers and is deciding whether to
**deliver** programs on Connect. The output is a JSON object
whose keys map to `{{placeholders}}` in `spec.template.yaml`. Fill every
placeholder.

This is the **other side of the marketplace** from `program-designer`.
That template answers "bring *your program* onto Connect"; this one
answers, from the delivery org's seat, **"what does it look like to
deliver on Connect, and why would I want to?"** The source of truth for
the messaging is **connect.dimagi.com** — the two-sided marketplace, the
org-side deal, real platform traction, and airtight, fair verification.

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

Lead with the things a delivery org actually weighs — in connect.dimagi.com's
own language:

0. **The frame: a two-sided marketplace.** Open on the website's line —
   *"Connect is a two-sided verified service delivery marketplace"* — pairing
   funders who want verified delivery with local organizations embedded in
   their communities. Put it in the hook; no analogies.
1. **The deal.** *"You bring the relationships and delivery capacity;
   Connect brings funding and technology."* Performance-based contracts,
   scaled against actual demand. This is the single most important beat.
2. **Proof it's real.** 1.5M+ verified services, 13 countries, 100+
   frontline organizations already delivering.
3. **Verification is airtight — and fair.** *"Verify every visit the moment
   it happens. No manual reviews, no delays, no fraud."* Biometric, GPS,
   photo. The on-brand integrity proof: *"97.5% of real workers scored
   cleaner than paid fakers in adversarial testing."* Frame it as protection
   for honest organizations.
4. **What you earn.** *"Pay only for verified delivery"* — and *"no
   intervention pays as much."*

## GROUNDING RULE

Carry only **real, cited facts from connect.dimagi.com**, never invented
ones — and prefer the website's exact wording. Safe figures + lines:

- 1.5M+ verified services; 13 countries; 100+ Frontline Organizations;
  10,000+ Frontline Workers trained; $2M+ paid to frontline workers.
- ~$1.70 per Child Health Campaign visit; "pay only for verified delivery,
  as low as $1.50 / service".
- 22% cost reduction per visit as programs scale; 85% of workers moved from
  training to delivery; <60s average verification.
- "97.5% of real workers scored cleaner than paid fakers in adversarial
  testing."
- Verification = biometric ID, GPS location, photo capture, data audits.

Never attribute a program-specific outcome to the LLO.

## Narration targets (per beat)

- `hook` (~14w): Connect is a two-sided marketplace for verified service
  delivery; you deliver and you're paid for every verified service.
- `cycle` (~14w): Learn, Deliver, Verify, Pay — one loop; paid for work
  delivered, not work promised.
- `handoff` (~8w): "here's what delivering on Connect looks like."
- `deal` → `narration.by_beat.ai_build` (~20w): you bring the relationships
  and delivery capacity, Connect brings funding and technology;
  performance-based contracts, scaled against demand.
- `scene` (~18w): workers deliver in their own communities — every service
  verified the moment it happens.
- `traction` → `narration.by_beat.problem` (~18w): not a pilot — 1.5M
  verified services, 13 countries, 100+ frontline organizations delivering.
- `product` (~30w): train with an AI coach, deliver guided visits — every
  service verified the moment it happens: biometric, GPS, photo; no manual
  reviews, no delays, no fraud.
- `impact` (~14w): pay only for verified delivery — no intervention pays as
  much; $2M+ paid to frontline workers.
- `cta`: leave empty — the outro plays under the brand CTA card.

## The deal card (ai_build beat)

- `deal_headline`: **one line, ≤7 words, benefit-first** — e.g. "Get paid
  for every verified service." Don't lead with an org name and don't let it
  wrap to two lines (it crowds the chips below).
- `deal_term_1..4`: the terms as chips, ≤ ~4 words each. Default (website
  framing): "Performance-based contracts", "Funding + technology, provided",
  "Paid on verification", "Scale against demand".
- `deal_subhead`: one line, e.g. "You bring the relationships; Connect
  brings funding and technology."

## Hero traction stat (problem beat)

- `traction_big` ≤ ~6 chars (e.g. "1.5M+"); `traction_caption` (what it
  counts, e.g. "verified services · 13 countries · 100+ organizations");
  `traction_source` (citation, e.g. "connect.dimagi.com").

## Traction cards (impact beat — TWO cards, REAL numbers)

Keep it to **two** cards so the stat beats don't blur together with the
hero traction stat above (four full-screen numbers in a row is stat
fatigue). Keep each `big` ≤ ~17 characters so it stays on one row at the
StatCard auto-fit size. Default pair — what an LLO most wants to know
(what you earn + the scale of payments already flowing):

- `impact_big_1` / `impact_caption_1`: pay — "$1.70" / "paid per verified
  visit".
- `impact_big_2` / `impact_caption_2`: scale of payments — "$2M+" / "paid
  to frontline workers".

## Library clips

This template references the standard workspace media-library clips via
`library:video/...` refs mapped through `manifest` `@alias` entries:

- scene.clips: `@field-walking-towards-house`, `@field-group-around-woman`
- product.beats (4): `@mobile-learn` (train), `@mobile-mapping` (deliver +
  GPS), `@web-superset-graphs` (audit dashboard), `@mobile-pay` (pay)

There are only four product slots (`product.beats` max 4) — the audit
dashboard clip is deliberately one of them; its caption carries the
website's integrity proof ("97.5% of real workers scored cleaner than paid
fakers"). Don't drop it for b-roll.

## Provenance

Fill `{{template_id}}` with `llo-deliver` and `{{generated_at}}` with an
ISO-8601 UTC timestamp.
