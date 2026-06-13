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

The viewer owns a real frontline program today and is deciding how to
scale it — possibly through Connect, in addition to or instead of scaling
their own delivery. The story is **how the program comes onto Connect +
the business case for scaling through it** (build once, replicate across
countries), with the Learn/Deliver/Verify/Pay loop shown as the program
*running*, not as an abstract product tour.

A great cut:

1. **Opens on the org's reality, not the product.** The hook is "you've
   built something that works; scaling it is the wall" — their POV.
2. **Shows the build, then the run.** The ai_build beat (AI cut) names the
   Connect components the program maps onto (training app, delivery app,
   verification rules, payment logic). Then scene + product show it
   running in the field and on the phone.
3. **Makes the business case explicit.** The `impact` beat is repurposed
   as three "why scale through Connect" benefit cards — built-for-scale,
   verified-delivery, pay-for-results. The why-narration says scaling
   through Connect is an option *alongside or instead of* their own teams.
4. **Names the AI features in product.** AI coach during Learn, AI-assisted
   review during Verify — the differentiators.

## GROUNDING RULE

Never invent numbers, and never attribute a program-specific OUTCOME to
the viewer's program. But DO put real, cited **platform** facts on screen
— they're about Connect, not the viewer's program, and they're the most
compelling material a program designer can hear. Safe, grounded facts:

- Build once → replicate: one program (CHC) reached **9 countries** with
  minimal additional development; 32 LLOs, 620k verified visits in a single
  quarter.
- **5 Health Ministries** signed on (DRC, Sierra Leone, Liberia, Uganda,
  Kenya) — governments trust it.
- 1.5M verified services, 13 countries, **10× year-on-year**, 200+ LLOs.
- Near-zero marginal cost to add each delivery partner (the marketplace
  model — think Airbnb for frontline delivery).
- **94%** population coverage with microplanning vs **84%** for seasoned
  implementers without it.

The single most compelling point for a program designer is **build once,
replicate across countries** — lead the business case with it.

## Narration targets (per beat)

- `hook` (~14w): you've built a working program; scaling to the last mile
  reliably is the hard part.
- `cycle` (~14w): name all four steps — Learn, Deliver, Verify, Pay — as
  the loop the program runs on.
- `handoff` (~8w): "here's how your program comes onto Connect."
- `ai_build` (~24w): AI turns the protocol into the program's apps, rules,
  and payments — then the payoff line: build it once, replicate it across
  countries. (AI cut only; harmless in standard.)
- `scene` (~18w): the field footage — workers reaching families, the work
  becoming visible end to end.
- `product` (~30w): walk the four app clips — AI coach in Learn, guided
  delivery, GPS + photo + AI review for Verify, automatic Pay — and land
  the 94%-vs-seasoned-implementers microplanning edge.
- `why` (~18w): build once, replicate across countries at near-zero cost
  per partner — it's how Connect reached 9 countries and 5 Health
  Ministries.
- `cta`: leave empty — the outro plays under the brand CTA card.

## AI-build card

- `ai_build_headline`: one punchy line, e.g. "AI turns your program into a
  Connect program — in days, not months."
- `ai_build_component_1..4`: the Connect components the program maps onto.
  Default: "Learn app", "Deliver app", "Verification rules", "Payment
  logic". 2–4 chips; keep each ≤ ~3 words so they fit on one row.
- `ai_build_subhead`: one line, e.g. "Your protocol, mapped onto Connect's
  rails."

## Why-scale benefit cards (impact beat)

Three cards carrying real, cited platform facts (most compelling first):

- `why_big_1` / `why_caption_1`: replicate — "9 countries" / "one program,
  replicated — minimal rebuild". The build-once-replicate story is the
  strongest point; lead with it.
- `why_big_2` / `why_caption_2`: trust — "5 Ministries" / "of Health signed
  on to Connect" (governments trust it).
- `why_big_3` / `why_caption_3`: the network — "200+ LLOs" / "a delivery
  network at near-zero cost".

(Older copy used numberless value props — "Verified delivery", "Pay for
results". Real cited facts land harder; keep them current, refresh ~yearly.)
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
