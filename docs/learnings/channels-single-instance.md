# Learning: InMemoryChannelLayer forces a single ECS Fargate task

**Date**: 2026-04-08
**Context**: Plan 1A `config/settings/base.py`. Blocker for scaling beyond a single instance.
**Status**: Active — deferred to Phase 3 (multi-player collaboration)

## Problem

`CHANNEL_LAYERS` in `config/settings/base.py` is set to `channels.layers.InMemoryChannelLayer`. This is a per-process in-memory layer, so any group-send from task A is invisible to task B. With more than one ECS Fargate task, WebSocket broadcasts silently vanish for half the connected clients.

The ECS desired-count must therefore stay at 1 until this is resolved.

## Root Cause

Channels requires a cross-process channel layer to broadcast across instances. The default `InMemoryChannelLayer` is fine for single-process dev but is not a production layer.

## Fix / Key Takeaway

Before raising the ECS desired-count above 1, Phase 3 (or whoever scales the service) must:

1. Add `channels-redis` to `pyproject.toml`
2. Override `CHANNEL_LAYERS` in `config/settings/connectlabs.py` (the active AWS prod settings module — `production.py` is currently dead code from the pre-AWS-migration era) with a `channels_redis.core.RedisChannelLayer` pointing at the shared connect-labs AWS ElastiCache Redis instance (free — already provisioned, no new infra required)
3. Raise the ECS desired-count

Do not increase the task count until all steps are done. A prominent WARNING comment exists in `config/settings/production.py`; if you move that file's responsibilities into `connectlabs.py`, carry the warning with it and keep it synchronized with the real state.
