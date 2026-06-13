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

0. **The frame: it's a marketplace.** Open on the Airbnb analogy —
   Connect is a marketplace for frontline delivery: it contracts, vets,
   and verifies LLOs without micromanaging them. This single image
   explains the whole model in one breath; put it in the hook.
1. **The deal.** Do I get paid, for what, and when? The deal card names
   it: a pay-per-service contract, no infrastructure to build, paid on
   verification, and a small trial run to start. This is the single most
   important beat.
2. **Proof it's real.** An LLO won't join a pilot promise. Lead with the
   strongest, most surprising facts: 1.5M verified services, 13 countries,
   10× a year, and FIVE Health Ministries signed on (governments trust
   it).
3. **That auditing is fair — the killer proof.** The most persuasive
   moment in the source material: *Connect paid workers to fake data, with
   cash prizes for the best fakes — and the model caught every one,
   flagging only 2.5% of honest workers.* Land this on the audit beat,
   verbatim-vivid. Frame it as protection for honest LLOs (disputes
   settled by data), not surveillance — that's what converts a skeptic.
4. **How to start small.** The trial-run chip makes the on-ramp explicit.

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

- `hook` (~14w): Connect is a marketplace for frontline delivery — think
  Airbnb; you deliver and you're paid for every verified visit.
- `cycle` (~14w): name all four steps — Learn, Deliver, Verify, Pay — as
  the loop your teams run.
- `handoff` (~8w): "here's what delivering on Connect looks like."
- `deal` → `narration.by_beat.ai_build` (~20w): Dimagi contracts your org
  and pays per verified service; you recruit and train workers, Connect
  verifies and pays. (The trial run lives on a chip — don't also say it here.)
- `scene` (~18w): field footage — workers reaching people, every visit
  verified the moment it happens.
- `traction` → `narration.by_beat.problem` (~18w): not a pilot — 1.5M
  verified services, 13 countries, 10× a year, five Health Ministries
  signed on.
- `product` (~30w): train with an AI coach, deliver guided visits — then
  the fraud-test proof: "we paid workers to fake data and caught them all;
  honest work is protected, you're paid on the proof."
- `impact` (~14w): Connect's microplanning reached 94% of people vs 84%
  without it — more reach, more verified visits, more pay.
- `cta`: leave empty — the outro plays under the brand CTA card.

## The deal card (ai_build beat)

- `deal_headline`: **one line, ≤7 words, benefit-first** — e.g. "Get paid
  for every verified service." Don't lead with an org name and don't let it
  wrap to two lines (it crowds the chips below).
- `deal_term_1..4`: the terms as chips, ≤ ~4 words each. Default:
  "Pay-per-service contract", "No infrastructure to build", "Paid on
  verification", "Start with a trial run".
- `deal_subhead`: one line, e.g. "Connect handles matching, verification,
  and payment — you focus on delivery."

## Hero traction stat (problem beat)

- `traction_big` ≤ ~6 chars (e.g. "1.5M"); `traction_caption` (what it
  counts, e.g. "verified services across 13 countries"); `traction_source`
  (citation, e.g. "Connect, 2026").

## Traction cards (impact beat — TWO cards, REAL numbers)

Keep it to **two** cards so the stat beats don't blur together with the
hero traction stat above (four full-screen numbers in a row is stat
fatigue). Keep each `big` ≤ ~17 characters so it stays on one row at the
StatCard auto-fit size. Default pair (lead with the outperformance — it's
the strongest "Connect makes your teams better" number):

- `impact_big_1` / `impact_caption_1`: outperformance — "94%" / "reached —
  vs 84% without Connect" (microplanning beats seasoned implementers).
- `impact_big_2` / `impact_caption_2` / `impact_source_2`: pay — "$1.30" /
  "average paid per verified visit" / "CHC Nigeria pilot" (cite it — the
  per-visit rate is program-specific, not a platform-wide average).

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
