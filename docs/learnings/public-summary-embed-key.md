# The public run summary serves the OCS embed key — deliberately

**Status:** accepted exposure, documented rather than removed (2026-08-14, PR #706).
**Decision owner:** Jonathan — flagged for review, not settled by the PR.

## What is exposed

`GET /api/opps/public/<ws>/<opp>/runs/<run>/summary` is served by
`public_summary_router = Router(auth=None)`. Its `assistant` block carries
`embed_key` alongside `public_id`, e.g. on
`dimagi-team/spark-facilitator/20260813-2126`:

```json
"assistant": {
  "public_id": "08a81855-…",
  "embed_key": "NQMdLB8o…"
}
```

Anyone who can load the summary URL can read the key. The URL is designed
to circulate — it is the surface we hand external partners.

## Why it is still there

The key is what the **browser-side** OCS widget authenticates with. Look at
`OcsWidgetMount`: it loads the Stencil component from unpkg and passes
`chatbot-id` + `embed-key` as DOM attributes. Any key the widget can use is,
by construction, a key the page's reader can read. There is no server-side
mode of that widget to hide it behind.

Removing it from the payload therefore removes the "Need help?" assistant —
which for an external reviewer is the single interactive thing on the page.
The obvious "minimal fix" (serve the key only when the widget renders) is a
no-op: the widget renders exactly when the key is present.

## What the exposure actually is

The key authorises **starting chat sessions against this opportunity's
chatbot**. It is a per-chatbot public identifier, not an OCS account
credential: it cannot read other chatbots, other teams, or existing
transcripts. Two real consequences:

1. The same bot is used for our own QA, so third-party traffic lands in the
   same session list we read for QA verdicts.
2. We have not established what rate limiting OCS applies to widget session
   creation, so the ceiling on abuse is unknown to us.

## What would actually fix it

Both are OCS-side, not ace-web-side:

- a short-lived session token minted server-side (ace-web proxies session
  creation, hands the widget a token scoped to one conversation); or
- OCS-enforced per-chatbot rate limits + an origin allowlist on the embed
  key, so the key is only usable from `labs.connect.dimagi.com`.

Until one of those exists, the honest position is: this is a public
identifier on a page whose URL is already the secret. Recorded here so the
next person who finds it in the payload finds the reasoning too, rather than
re-deriving it or quietly deleting the widget.
