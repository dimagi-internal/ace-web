# Generator skill: program designer — bring your program onto Connect (generic)

You are filling out a video spec for a generic ~57-second explainer aimed
at a **program designer** — an org that owns a frontline program/protocol
— that answers two questions at once: **what does it look like to bring an
existing program onto Connect**, and **why scale through Connect
at all?** The output is a JSON object whose keys map to `{{placeholders}}`
in `spec.template.yaml`. Fill every placeholder.

This is the **unbranded backbone** of the partnership pitch. Keep it
generic — no prospect name, no single program's outcomes — so it can be
skinned per prospect later (partnership-pitch adds the prospect block).
For the other side of the marketplace — a local org deciding whether to
*deliver* on Connect — use the `llo-deliver` template instead.

## The two cuts (one spec)

This template renders from `active_cut`:

- `active_cut: ai` — the **AI cut**. Includes the `body_ai_build` beat:
  a card that says Connect's AI design tooling turns the org's program
  into its Connect components. ~57s, 8 beats.
- `active_cut: standard` — the **non-AI cut**. The `body_ai_build` beat is
  dropped; everything else is identical. ~50s, 7 beats.

Author the `ai_build` block and the `narration.by_beat.ai_build` line
regardless — they're simply unused in the standard cut. Default the
example to `ai` unless told otherwise.

## What this video is for (and what makes it good)

The viewer owns a real frontline program today and is deciding how to bring
it onto Connect. Tell the story in **connect.dimagi.com's own language**:
pay for verified delivery (not planned activity), deploy in as few as 10
days, then scale against demand. Show the Learn/Deliver/Verify/Pay loop
*running*, not as an abstract product tour.

A great cut:

1. **Opens on the shift, not the product.** The website's framing: "For
   decades, funders paid for planned activity and hoped it added up. Connect
   pays for work delivered, not work promised."
2. **Shows rapid setup, then the run.** The ai_build beat (AI cut) names the
   infrastructure Connect provides (training, delivery app, verification,
   payments) and the headline number — deployed in as few as 10 days. Then
   scene + product show it running.
3. **Makes the business case explicit.** The `impact` beat is three cards of
   cited facts: speed (10 days to first deployment), the economics of scale
   (22% cost reduction per visit), and proof of scale (1.5M+ verified
   services across 13 countries).
4. **Names the AI + verification.** AI coach during Learn; biometric, GPS,
   and photo verification "the moment it happens".

## GROUNDING RULE

Never invent numbers, and never attribute a program-specific OUTCOME to the
viewer's program. DO put real, cited **platform** facts from
connect.dimagi.com on screen — prefer the website's exact wording:

- "Rapid deployment in as few as 10 days"; "Scale up against actual demand".
- "22% cost reduction per visit as programs scale".
- 1.5M+ verified services; 13 countries; 100+ Frontline Organizations;
  10,000+ Frontline Workers trained; $2M+ paid to frontline workers.
- "Pay for verified service delivery, not planned activity"; "Connect pays
  for work delivered, not work promised".
- "funders track exactly what was delivered, where, and at what cost".
- Verification: biometric ID, GPS, photo, data audits — "the moment it happens".

## Narration targets (per beat)

- `hook` (~14w): for decades programs paid for planned activity and hoped it
  added up; Connect pays for verified delivery.
- `cycle` (~14w): pick the program, geography, and amount — then it runs as
  one loop: Learn, Deliver, Verify, Pay.
- `handoff` (~8w): "here's how your program comes onto Connect."
- `ai_build` (~24w): Connect provides the app, training, verification, and
  payments — your program deployed in as few as 10 days, then scaled against
  demand. (AI cut only; harmless in standard.)
- `scene` (~18w): frontline workers deliver in their own communities — and
  you see exactly what was delivered, where, and at what cost.
- `product` (~30w): walk the four app clips — AI coach in Learn, deliver,
  verify the moment it happens (biometric, GPS, photo), pay for every
  verified service.
- `why` (~18w): deployed in as few as 10 days, then scaled against demand —
  costs falling 22% per visit as programs grow.
- `cta`: leave empty — the outro plays under the brand CTA card.

## AI-build card

- `ai_build_headline`: one punchy line, e.g. "Deployed in as few as 10 days".
- `ai_build_component_1..4`: the infrastructure Connect provides. Default:
  "Training", "Delivery app", "Verification", "Payments". 2–4 chips; keep
  each ≤ ~3 words so they fit on one row.
- `ai_build_subhead`: one line, e.g. "Connect provides the infrastructure;
  you bring the program."

## Why-scale benefit cards (impact beat)

Three cards carrying real, cited facts from connect.dimagi.com (most
compelling first):

- `why_big_1` / `why_caption_1`: speed — "10 days" / "to first deployment".
- `why_big_2` / `why_caption_2`: economics of scale — "22%" / "cost
  reduction per visit as you scale".
- `why_big_3` / `why_caption_3`: proof of scale — "1.5M+" / "verified
  services across 13 countries".
Keep each `big` ≤ ~17 characters so it stays on one row at the StatCard
auto-fit size.

## Library clips

This template references the standard workspace media-library clips via
`library:video/...` refs mapped through `manifest` `@alias` entries. The
clips wired in the skeleton:

- scene.clips: `@field-walking-towards-house`, `@field-group-around-woman`
- product.beats (4): `@mobile-learn`, `@mobile-mapping` (GPS),
  `@web-microplan` (NM verification review), `@mobile-pay`

Spare scene clips you may add (scene.clips max 6):
`field-walking-in-market-flws.mp4`, and `web-superset-graphs.mp4` for a
dashboard moment. There are only four product slots (`product.beats`
max 4) — don't drop an app beat to fit b-roll.

## Provenance

Fill `{{template_id}}` with `program-designer` and `{{generated_at}}`
with an ISO-8601 UTC timestamp.
