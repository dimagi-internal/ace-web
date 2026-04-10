# Learning: InMemoryChannelLayer forces a single ECS Fargate task

**Date**: 2026-04-08
**Context**: Plan 1A `config/settings/base.py`. Blocker for scaling beyond a single instance.
**Status**: Resolved and scaled past single-instance (2026-04-09). ECS desired-count raised to 2; cross-task `channels-redis` broadcast verified via ECS exec on both tasks.

## Resolution

Phase 3 completed all three steps listed in the Fix section below:

1. `channels-redis` added to `pyproject.toml` (Task 1).
2. `CHANNEL_LAYERS` now points at `channels_redis.core.RedisChannelLayer` in
   `config/settings/connectlabs.py`, reading `REDIS_URL` from env (Task 2,
   commit `a12d5c3`). Local dev uses the same key against the Docker Compose
   Redis service. See `docs/learnings/redis-presence-hash.md` for the
   presence-specific usage of the same Redis instance.
3. Shared ElastiCache wired into the ECS task via `REDIS_URL` in Secrets
   Manager (Task 13); ingress from the ECS security group is open on 6379.

ECS desired-count was raised to 2 on 2026-04-09. Cross-task broadcast
verified via ECS exec: both tasks (`ip-10-0-1-247` in us-east-1b,
`ip-10-0-2-181` in us-east-1a) successfully PING Redis, complete a
`RedisChannelLayer` group_send/receive round-trip, and see each other's
probe keys. ECS exec is now enabled on all services in `labs-jj-cluster`
(IAM policy `ecs-exec-ssm` on `labs-jj-ecs-task-role`).

The original Problem / Root Cause / Fix sections below are kept as
historical context so the resolution story is traceable.

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
