# slack-integration

Practical traps caught while building the v1 Slack integration (2026-05-15).

## Runtime / worker guards

- **`SlackConfig.ready()` runs in every Django management command, including
  `manage.py migrate`, `pytest`, and `makemigrations`**. Starting the async
  worker in those contexts will either fail (no event loop) or, worse, fire
  `chat.update` calls during test runs. Guard with all three:
  `DJANGO_SLACK_DISABLE_WORKER=1`, `"pytest" in sys.modules`, and
  `"migrate" in sys.argv`.

- **`asyncio.get_running_loop()`, not `get_event_loop()`** — `get_event_loop()`
  is deprecated in Python 3.10+ and raises `DeprecationWarning` (soon an error)
  when there is no current event loop. The Slack worker is now wired via the
  ASGI lifespan in `config/asgi.py` (not `SlackConfig.ready()`), where a
  running loop is always guaranteed. Avoid spawning async tasks from
  `AppConfig.ready()` — no event loop is available there.

## Slack API behavior

- **`channel_not_found` is silent.** Slack returns HTTP 200 with `ok=false` and
  the error string in the body — `slack_sdk` raises `SlackApiError`. The wrapper
  in `apps/slack/slack_client.py` normalises this to `SlackChannelGone`; the
  dispatcher marks the thread `broken_at` and stops posting.

- **`chat.update` on a `ts` from a different channel returns `message_not_found`,
  not the obvious error.** Always store `(channel_id, ts)` together in
  `SlackRunThread` and pass both on every update call.

- **`response_type` semantics differ between slash commands and block_actions.**
  Omitting `response_type` on slash-command responses defaults to `ephemeral`,
  which is what we want. For `block_actions` payloads, `response_type` in the
  JSON body is ignored — use `response_url` POST or an explicit ephemeral
  `response_action: "clear"` pattern instead.

- **Slack rate-limit is per-method-per-channel.** The 2-second debounce plus
  per-thread dispatch is enough for a single run, but a busy channel with many
  concurrent runs could still trigger tier-1 limits. Watch `slack.rate_limited`
  log lines in CloudWatch.

## Concurrency / Redis

- **Per-tick dedup lock must be `cache.add` (SETNX), not `cache.set`.**
  `cache.set` overwrites any existing value, so every ECS task wins the "lock"
  and all run the tick simultaneously — exactly the race you're trying to
  prevent. `cache.add` is atomic and returns `False` when the key already
  exists.

## Model field names (test trap)

- **Plan test fixtures used `Workspace(name=...)` but the model field is
  `display_name`.** Multiple plan-provided test fixtures passed `name=` to
  `Workspace.objects.create(...)` and caused `TypeError`. The correct field is
  `display_name`, matching the `Workspace` model definition in
  `apps/workspaces/models.py`.

- **`SlackInstallation` has no `set_bot_token` method — assign the property
  directly.** Plan drafts referenced `inst.set_bot_token("xoxb-...")` but the
  model exposes `bot_token` as a plain encrypted property (via
  `django-cryptography`). The correct pattern is `inst.bot_token = "xoxb-..."`
  followed by `inst.save()`.

## Snapshot access path

- **Use `load_opp_snapshot` from `apps.opps.api`, not `get_snapshot`.**  The
  dispatcher's `_load_snapshot` helper wraps
  `apps.opps.api.load_opp_snapshot(workspace, slug, run_id=...)`. Earlier plan
  drafts referenced a non-existent `get_snapshot` primitive. The real function
  path is `apps/opps/api.py::load_opp_snapshot`.

## Run ID format

- **`run_id` is timestamp-based (`YYYYMMDD-HHMM`), not sequential (`run-NNN`).**
  Early plan drafts used `run-001` as fixture values for `run_id`. While these
  work as arbitrary string fixtures in tests, the real ACE plugin mints run IDs
  as `YYYYMMDD-HHMM` timestamps (same format `/ace:run` uses). Idea/PDD paths
  via `create_opp` do currently hardcode `"run-001"` as the initial run, but
  subsequent runs follow the timestamp pattern. Don't assume sequential numbering
  when writing queries or UI display logic.
