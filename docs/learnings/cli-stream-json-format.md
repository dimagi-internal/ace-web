# Learning: Claude CLI stream-json output format

**Date**: 2026-04-08
**Context**: Phase 2 CLIBackend parses `claude -p --output-format stream-json` output. The format is an external dependency we should pin via fixtures.
**Status**: Active — fixtures are shaped from documentation, not captured from a real CLI run. **TODO**: recapture against a real `claude -p` invocation and verify the parser accepts it byte-identically.

## Problem

The Claude Code CLI's `stream-json` output format is JSON-Lines but the event shapes are not formally documented. ace-web's `apps/common/cli_event_parser.py` parses these events into `StreamEvent` records; if the CLI changes its event shapes, the parser breaks and we get garbled chat.

## Root Cause

External dependency on a CLI output format that has no stability contract.

## Fix / Key Takeaway

Fixtures are committed at `apps/common/tests/fixtures/stream_json_*.txt`. The parser tests run against these fixtures, so any format drift surfaces as a test failure.

Event shapes as understood at the time Phase 2 shipped:

- `{"type": "system", "subtype": "init", "session_id": "<id>", ...}` — first event of every fresh session, contains the new CLI session id
- `{"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}` — assistant text deltas (one event per chunk, may contain multiple blocks per message which the parser now iterates)
- `{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "...", "name": "...", "input": {...}}]}}` — tool use blocks
- `{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "...", "content": "..."}]}}` — tool result blocks
- `{"type": "result", "subtype": "success", ...}` — terminal "done" event
- `{"type": "result", "subtype": "error_..."}` — terminal error variant (anything else falls through to done with a warning log, per the forward-compat fix in Task 2)

### How to recapture fixtures

```bash
# In a container with claude CLI installed and authenticated:
echo "What is 2+2?" | claude -p --output-format stream-json > apps/common/tests/fixtures/stream_json_simple.txt
# Review the file, verify the parser tests still pass:
.venv/bin/pytest apps/common/tests/test_cli_event_parser.py -v
```

If the parser tests fail after recapturing, update `cli_event_parser.py` to match the real shape and this document.
