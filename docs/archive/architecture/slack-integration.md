# Slack integration — operator runbook

## Install the Slack app (one-time)

1. Create a Slack app at https://api.slack.com/apps with the following:
   - Bot scopes: `commands`, `chat:write`, `users:read`, `users:read.email`,
     `channels:read`, `groups:read`
     (intentionally NO `chat:write.public` — bot must be invited to a
     channel before `/ace` commands work there. `channels:read` and
     `groups:read` power the bot-member-only channel picker surfaced by
     the **Push to Slack** action on PhaseView.)
   - Slash command `/ace` pointing at
     `https://labs.connect.dimagi.com/ace/api/slack/commands`
   - Interactivity request URL: `https://labs.connect.dimagi.com/ace/api/slack/interactions`
   - Events request URL: `https://labs.connect.dimagi.com/ace/api/slack/events`
     - Subscribe to bot event `app_home_opened` to enable the **App Home
       tab** (per-user dashboard showing tracked runs + workspace
       activity + quick actions).
   - App Home: enable the **Home Tab**. Disable the Messages tab and the
     "Allow users to send Slash commands and messages from the messages
     tab" toggle — we don't subscribe to message events.
2. Copy `Client ID`, `Client Secret`, `Signing Secret` into AWS Secrets Manager
   under the existing ace-web secret, keyed `SLACK_CLIENT_ID`,
   `SLACK_CLIENT_SECRET`, `SLACK_SIGNING_SECRET`. Run the labs deploy workflow.
3. As a Django superuser, visit `https://labs.connect.dimagi.com/ace/api/slack/install`
   and approve the install. This creates the `SlackInstallation` row in the
   `dimagi-team` workspace. After the install completes, the **Slack** panel
   on `/w/<slug>/workspace-settings` shows the connection state; reconnect
   from there after scope changes.

### After scope changes (e.g. when this doc was updated)

When bot scopes change, existing installs keep working but won't have the
new scope until reinstalled. To pick up `channels:read` + `groups:read`
for an existing install:

1. Edit the Slack app's bot scopes at api.slack.com.
2. Visit `/ace/api/slack/install` as a superuser — Slack will re-prompt
   for approval and update the bot token in place. The Reconnect button
   on the Workspace Settings → Slack panel kicks off the same flow.

## Per-user account linking

The first time a Slack user runs `/ace …`, the bot DMs them a link. The link
goes to `https://labs.connect.dimagi.com/ace/auth/slack/link/?nonce=…` and
requires the standard Connect OAuth login. On success, a `SlackUserLink` row is
created and the original command is replayed.

To force a re-link, the user can run `/ace link`.

## Day-to-day flows

| Command                              | What it does                                                  |
| ------------------------------------ | ------------------------------------------------------------- |
| `/ace run <slug>`                    | Start `/ace:run` on an existing opp.                          |
| `/ace run <pdd-link>`                | Create an opp from a PDD in Drive and run it.                 |
| `/ace new`                           | Open a modal: name + idea → new opp.                          |
| `/ace track <slug>[/<run_id>]`       | Mirror an existing run (e.g. one running on a laptop) into the current channel. Bare slug picks the current run. |
| `/ace untrack <slug>`                | Stop mirroring. Equivalent to clicking *Stop watching* on the parent card. |
| `/ace status [<slug>]`               | Ephemeral parent-card snapshot.                               |
| `/ace list`                          | Top 5 active runs the user triggered.                         |
| `/ace link`                          | Re-issue the OAuth-link DM.                                   |
| `/ace help`                          | Print usage.                                                  |

### Tracking laptop-driven runs

`/ace track` exists for runs that aren't driven through ace-web's
`turn_driver` — typically when a human is running `claude -p /ace:run`
on their laptop. There's no `opp.updated` push signal for those runs, so
the dispatcher's 30s periodic sweep is the only progress source.
`dispatch_tick` re-loads the opp snapshot, which goes through the Drive
Changes API (per the opp-cache redesign) and picks up Drive-only changes
automatically. Cost is ~30ms per active tracked thread per sweep tick.

Click *Stop watching* on the parent card (or run `/ace untrack <slug>`)
to stop mirroring; the run itself keeps going. The thread is marked with
`stopped_at` and the sweep skips it from then on.

## Troubleshooting

- **`signature mismatch` in logs**: rotate or re-paste `SLACK_SIGNING_SECRET`
  in Secrets Manager and redeploy.
- **`channel_not_found` on update**: bot was removed from the channel.
  `SlackRunThread.broken_at` is set; the user must `/ace run` again from a
  channel where the bot is present.
- **Thread not updating but the run is progressing on the Workbench**: check
  that the ASGI worker started — look for `_run_worker` in the logs. If
  missing, the `SlackConfig` `ready()` skipped startup (test/migrate detection
  is a heuristic). Set `DJANGO_SLACK_DISABLE_WORKER=0` in the task definition
  and redeploy.
- **Duplicate updates**: the per-tick Redis lock should prevent this. If you
  see them, `redis-cli KEYS 'slack:dispatch:*'` and `DEL` any stale entries.

## Architecture summary

See `docs/superpowers/specs/2026-05-15-slack-integration-design.md`. Key
reuse: the existing `opp.updated` channel-layer group from
`apps/sessions/opp_broadcast.py` is the progress signal — the
`SlackOppConsumer` worker just adds itself as a second listener alongside
the browser's `OppConsumer`.

## Web surfaces

Three web surfaces tie the Slack integration to the rest of ace-web:

- **Workspace Settings → Slack panel** (`/w/<slug>/workspace-settings`):
  status badge + "Add to Slack" CTA when missing; Reconnect / Open
  Block Kit preview when installed. Backed by `GET /api/w/<slug>/slack/status`.
- **PhaseView → Push to Slack button**: in the phase header next to
  "Fork from here". Opens a channel picker populated from bot-member
  channels (`GET /api/w/<slug>/slack/channels`), then `POST
  /api/w/<slug>/slack/push-phase` posts the parent card + phase tile
  and creates a `SlackRunThread` so subsequent updates flow through the
  existing mirror loop. When a thread already exists for the (opp, run),
  the button switches to "Tracked in Slack" with a deep link.
- **Slack App Home tab**: published per-user on `app_home_opened`.
  Linked users see tracked runs + workspace activity + quick action
  buttons; unlinked users see a Link Account CTA. Builder is in
  `apps/slack/home_view.py`.
