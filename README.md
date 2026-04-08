# ace-web

The web harness for the ACE (AI Connect Engine / CRISPR-Connect) initiative.

Module 1 of the larger ACE web system — a browser-based chat harness that talks
to Claude via the local CLI (subscription auth) with multi-player drafts,
persistent transcripts, and upload support for existing local `.jsonl` sessions.

## Where things live

- **Implementation plans** (per-module): `ace-web/docs/plans/`
- **Architecture spec**: no unified web-harness spec file exists yet. Per-wave
  scope is defined in the plan file for that wave.

This repo is consumed as a git submodule from the `ace` repo so cross-module
work (plan updates, spec references) can happen in one checkout. Day-to-day
implementation work on ace-web itself should happen in this repo directly —
not through the ace worktree — to avoid submodule pointer churn.

## Quick start (local dev)

```bash
docker compose up
```

Then open http://localhost:8000.

## Stack

- Django 5 + Channels 4 + DRF (ASGI via uvicorn)
- React 19 + Vite + Tailwind 3.4
- PostgreSQL in Cloud SQL
- Deployed on GCP Cloud Run behind IAP + Google SSO

## Current status

Plan 1A (foundation) complete. See `docs/plans/2026-04-07-1a-foundation.md`
for the full task list and the post-execution corrections section documenting
all the review findings applied during execution.

Plans 1B (single-player chat), 1C (multi-player + drafts), and 1D (transcript
library + share + ingest) are next.
