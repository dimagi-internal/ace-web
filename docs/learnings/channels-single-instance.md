# Learning: InMemoryChannelLayer forces Cloud Run to a single instance

**Date**: 2026-04-08
**Context**: Plan 1A `config/settings/base.py` and `cloudbuild.yaml`. Blocker for scaling beyond `max-instances=1`.
**Status**: Active — deferred to Plan 1C

## Problem

`CHANNEL_LAYERS` in `config/settings/base.py` is set to `channels.layers.InMemoryChannelLayer`. This is a per-process in-memory layer, so any group-send from instance A is invisible to instance B. With more than one Cloud Run instance, WebSocket broadcasts silently vanish for half the connected clients.

`cloudbuild.yaml` therefore pins the service to `--min-instances=1 --max-instances=1`. This is enforced at the infra level so a reader of the config file understands why scaling is constrained, not just "oh, it's cheap".

## Root Cause

Channels requires a cross-process channel layer to broadcast across instances. The default `InMemoryChannelLayer` is fine for single-process dev but is not a production layer.

## Fix / Key Takeaway

Before raising `max-instances` above 1, Plan 1C (or whoever scales the service) must:

1. Add `channels-redis` to `pyproject.toml`
2. Provision a Memorystore Redis instance in the same VPC as Cloud Run
3. Replace `CHANNEL_LAYERS` in `config/settings/production.py` with a `channels_redis.core.RedisChannelLayer` pointing at the Memorystore instance
4. Relax `--max-instances=1` in `cloudbuild.yaml`

Do not remove the single-instance pin until all four steps are done. A prominent WARNING comment already exists in `config/settings/production.py` — keep it synchronized with the real state.
