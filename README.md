# ace-web

The web harness for the ACE (AI Connect Engine / CRISPR-Connect) initiative.

Module 1 of the larger ACE web system. The full design and implementation plan
live in the sibling `ace` repo at:

- Spec: `ace/docs/superpowers/specs/2026-04-07-ace-web-harness-design.md`
- Plan 1A (foundation): `ace/docs/superpowers/plans/2026-04-07-ace-web-1a-foundation.md`

This repo is consumed as a git submodule from the `ace` repo so that worktrees
of `ace` automatically have the matching `ace-web` checkout available.

## Quick start (local dev)

```bash
docker compose up
```

Then open http://localhost:8000.

## Stack

- Django 5 + Channels + DRF (ASGI via uvicorn)
- React 19 + Vite + Tailwind 4
- PostgreSQL
- Deployed on GCP Cloud Run + Cloud SQL behind IAP

## Submodule URL

This repo is currently referenced from `ace` via a local `file://` URL. When
the repo is pushed to a remote, update the submodule URL in `ace/.gitmodules`
and run `git submodule sync` in any clone.
