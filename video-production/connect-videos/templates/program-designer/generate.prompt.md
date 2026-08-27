# Generator skill: program designer — bring your program onto Connect (generic)

You are filling out a video spec for a generic ~57-second explainer aimed
at a **program designer** — an org that owns a frontline program/protocol
— that answers two questions at once: **what does it look like to bring an
existing program onto Connect**, and **why scale through Connect
at all?** You are given this template's **example spec** — a complete,
renderable `spec.yaml` — and must produce a new `spec.yaml` of the **same
structure**. Keep the example's beat structure and brand scaffolding, and
replace only the program-specific content per the guidance below.

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

**TONE — explainer, not a pitch.** The viewer owns a real frontline program,
already knows and likes Connect (they've had a real intro call), and wants
to understand how their program would run on it. Walk them calmly through
the mechanism — the loop, what Connect provides, how a visit gets verified
and paid. Avoid persuasion framing ("for decades… hoped it added up"),
proof-point stat barrages (10 days / 22% / scale numbers), and speed/scale
brags. Show the Learn/Deliver/Verify/Pay loop *running*.

A great cut:

1. **Opens calmly on the topic, not a pitch.** The hook just frames it:
   "here's how a program runs on Connect — and what bringing yours over
   looks like."
2. **Shows what Connect provides, then the run.** The ai_build beat (AI cut)
   names the pieces Connect sets up around the program (training, delivery
   app, verification, payments). Then scene + product show it running.
3. **Explains what you get.** The `impact` beat is three plain mechanism
   cards: verified delivery (biometric, GPS, photo), paid-on-proof, and full
   visibility (what was delivered, where, and at what cost).
4. **Names the AI + verification plainly.** AI coach during Learn; biometric,
   GPS, and photo verification.

## GROUNDING RULE

Never invent numbers, and never attribute a program-specific OUTCOME to the
viewer's program. Plain facts (terminology may follow connect.dimagi.com)
are fine as *context* — but keep them factual, not a sell: Connect provides
training / the delivery app / verification / payments; verification is
biometric, GPS, photo, data audits; payment follows verification; the viewer
sees what was delivered, where, and at what cost. Skip the persuasion lines
("planned activity… hoped it added up", "rapid deployment in as few as 10
days", "22% cost reduction") — they read as a pitch to an audience that's
already sold.

## Narration targets (calm explainer; per beat)

- `hook` (~14w): here's how a program runs on Connect — and what bringing
  yours over looks like.
- `cycle` (~12w): every program runs the same loop: Learn, Deliver, Verify,
  and Pay.
- `handoff` (~8w): "here's how your program comes onto Connect."
- `ai_build` (~20w): Connect provides the pieces — training, the delivery
  app, verification, and payments — set up around your program. (AI cut
  only; harmless in standard.)
- `scene` (~16w): frontline workers deliver in their own communities, and
  every visit is recorded as it happens.
- `product` (~26w): workers learn on their phones with an AI coach, deliver
  guided visits, and each one is verified — biometric, GPS, and photo; then
  payment follows.
- `why` (~18w): once a visit is verified, payment follows automatically — and
  you can see exactly what was delivered, where, and at what cost.
- `cta`: leave empty — the outro plays under the brand CTA card.

## "What Connect provides" card (ai_build beat)

- `ai_build_headline`: short and plain, e.g. "What Connect provides".
- `ai_build_component_1..4`: the pieces Connect sets up. Default:
  "Training", "Delivery app", "Verification", "Payments". 2–4 chips; keep
  each ≤ ~3 words so they fit on one row.
- `ai_build_subhead`: one line, e.g. "Set up around your program; you bring
  the protocol."

## "What you get" cards (impact beat)

Three plain mechanism cards (how it works, not a sell):

- `why_big_1` / `why_caption_1`: verification — "Verified" / "every visit —
  biometric, GPS, photo".
- `why_big_2` / `why_caption_2`: payment — "Paid on proof" / "funds follow
  verified delivery".
- `why_big_3` / `why_caption_3`: visibility — "Full visibility" / "what was
  delivered, where, and at what cost".
Keep each `big` ≤ ~17 characters so it stays on one row at the StatCard
auto-fit size.

## Library clips

This template references the standard workspace media-library clips via
`library:video/...` refs mapped through `manifest` `@alias` entries. The
clips wired in the example:

- scene.clips: `@field-walking-towards-house`, `@field-group-around-woman`
- product.beats (4): `@mobile-learn`, `@mobile-mapping` (GPS),
  `@web-microplan` (NM verification review), `@mobile-pay`

Spare scene clips you may add (scene.clips max 6):
`field-walking-in-market-flws.mp4`, and `web-superset-graphs.mp4` for a
dashboard moment. There are only four product slots (`product.beats`
max 4) — don't drop an app beat to fit b-roll.

## Provenance

Set `provenance.template` (and `provenance.generator`) to `program-designer`
and `provenance.generated_at` to an ISO-8601 UTC timestamp.
