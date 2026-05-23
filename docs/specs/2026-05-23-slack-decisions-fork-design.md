# Slack Multi-Player Decisions & Fork

**Status:** Active
**Date:** 2026-05-23

## Problem

The Slack integration currently shows a count of open decisions (`:grey_question: 2 open`)
but no question text, no AI defaults, and no way to interact. The "Fork from here" button
just redirects to ace-web. For someone watching in Slack who doesn't know ace-web, this is
opaque — they see a number tick, have no idea what the question is, and can't act on it.

## Solution

Render each decision as its own thread-reply message with interactive option buttons.
Anyone in the channel can vote (last-write-wins, everyone sees who picked what). When
votes are collected, a "Fork & re-run with answers" button on the phase tile fires the
fork with the voted answers as edits.

## Architecture

### Data: votes stored on SlackRunThread.phase_messages (existing JSONField)

Each phase entry gains two new keys alongside the existing `ts` and `last_state_hash`:

```yaml
idea-to-design:
  ts: "1234.5678"
  last_state_hash: "abc..."
  decision_messages:       # decision_id → Slack message metadata
    d-001: { ts: "1235.0" }
    d-002: { ts: "1236.0" }
  votes:                   # decision_id → current effective answer
    d-001: { answer: "Option B", voter_slack_id: "U12345", voter_name: "Alice" }
```

No new tables. No migration. Votes are ephemeral state that only matters until the fork
commits them into `decisions.yaml` in the new run.

### Rendering: per-decision thread replies

Each decision gets its own message posted as a reply to the phase tile (using `thread_ts`).
Structure per message (~4-5 blocks):

- **Context block**: `📋 Decision #3 · draft-pdd`
- **Section block**: question text (bold) + AI default as quoted line
- **Context block**: voter line — `💬 @alice → Option B` (updates on each vote via
  `chat.update`; initially "No answer yet")
- **Actions block**: one button per `options_considered` entry (capped at 4, reserving 1
  slot for "Other..." which opens a modal with text input)

This scales to any number of decisions — no 50-block-per-message pressure.

### Phase tile changes

The existing `render_phase_tile` gains a decision summary line when decisions exist:

```
📋 20 decisions · 4 answered by 2 people
```

The "Fork from here..." button is replaced by "Fork & re-run with answers" when
`len(votes) > 0`. This button fires the fork directly (async via `response_url`).
When there are zero votes and the phase has completed steps, the existing redirect-
to-ace-web behavior is preserved.

### Dispatcher changes

`dispatch_tick` is extended: after rendering/updating phase tiles, for each phase with
decisions in the snapshot, diff the snapshot's decision list against `decision_messages`
in the thread metadata. New decisions get posted as thread replies; existing decisions
with changed vote state get `chat.update`d.

A new hash field (`decisions_hash`) on the phase entry captures the vote state so
unchanged decisions don't trigger Slack API calls.

### Interaction handlers (new)

Two new `block_actions` handlers in `dispatch_interaction`:

1. **`answer_decision`**: button click on an option. Value encodes
   `opp_slug:phase:decision_id:answer_text`. Handler:
   - Resolves the `SlackRunThread` from the thread context
   - Records the vote in `phase_messages[phase].votes[decision_id]`
   - `chat.update`s the decision message to show the voter
   - `chat.update`s the phase tile to refresh the summary counts
   - Returns 200

2. **`answer_decision_other`**: "Other..." button opens a modal
   (`views.open`). `view_submission` handler reads the text input, records the vote
   the same way.

One new `block_actions` handler for fork:

3. **`fork_with_answers`**: collects all votes from
   `phase_messages[phase].votes`, maps them to `OppForkIn.edits`, calls
   `fork_opp_and_return` (existing helper). Since fork is Drive-heavy
   (5-15s), return 200 immediately and POST the result back via `response_url`.
   The fork result message includes a link to the new run in ace-web and
   optionally starts tracking the new run in the same channel.

### Permissions

Any user with a `SlackUserLink` (i.e. who has completed `/ace link`) can vote and fork.
No workspace-role check. Matches the current Slack integration's permission model.

### Conflict resolution

Last-write-wins. When Alice picks Option A and then Bob picks Option B for the same
decision, the message updates to show Bob's choice. Both see the change. The fork
button commits whatever's current at click time.

### Block Kit limits

- Max 5 elements per `actions` block → cap `options_considered` buttons at 4 + "Other..."
- Max 50 blocks per message → only the phase tile is affected (decisions are separate messages)
- Decisions with >4 options: show first 4 buttons + "Other..." modal (which has a text input, so any answer is reachable)

## Files to create/modify

**New:**
- `apps/slack/blocks_decisions.py` — `render_decision_message()`, `render_decision_summary()`, `decisions_state_hash()`
- `apps/slack/verbs_decisions.py` — `handle_answer_decision()`, `handle_answer_other_submission()`, `handle_fork_with_answers()`
- `apps/slack/tests/test_blocks_decisions.py`
- `apps/slack/tests/test_handlers_decisions.py`

**Modified:**
- `apps/slack/blocks.py` — `render_phase_tile()` gains decision summary line + fork button variant
- `apps/slack/dispatcher.py` — `dispatch_tick()` extended to post/update decision messages
- `apps/slack/handlers.py` — `dispatch_interaction()` routes new action_ids

## Testing

- Unit tests for all renderers (pure JSON assertions)
- Unit tests for interaction handlers (mock SlackClient + Drive)
- Generate Block Kit JSON fixtures for manual visual preview in Slack's Block Kit Builder
- Integration: `/ace track` an opp with decisions, verify messages appear, click buttons, fork
