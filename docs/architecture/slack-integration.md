# Slack integration — operator runbook

## Install the Slack app (one-time)

1. Create a Slack app at https://api.slack.com/apps with the following:
   - Bot scopes: `commands`, `chat:write`, `chat:write.public`, `users:read`, `users:read.email`
   - Slash command `/ace` pointing at
     `https://labs.connect.dimagi.com/ace/api/slack/commands`
   - Interactivity request URL: `https://labs.connect.dimagi.com/ace/api/slack/interactions`
   - Events request URL: `https://labs.connect.dimagi.com/ace/api/slack/events`
     (only used today for `url_verification`).
2. Copy `Client ID`, `Client Secret`, `Signing Secret` into AWS Secrets Manager
   under the existing ace-web secret, keyed `SLACK_CLIENT_ID`,
   `SLACK_CLIENT_SECRET`, `SLACK_SIGNING_SECRET`. Run the labs deploy workflow.
3. As a Django superuser, visit `https://labs.connect.dimagi.com/ace/api/slack/install`
   and approve the install. This creates the `SlackInstallation` row in the
   `dimagi-team` workspace.

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
| `/ace status [<slug>]`               | Ephemeral parent-card snapshot.                               |
| `/ace list`                          | Top 5 active runs the user triggered.                         |
| `/ace link`                          | Re-issue the OAuth-link DM.                                   |
| `/ace help`                          | Print usage.                                                  |

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
