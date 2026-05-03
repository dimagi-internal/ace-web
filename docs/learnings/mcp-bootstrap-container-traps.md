# Learning: MCP bootstrap traps in the deployed container

**Date**: 2026-05-02
**Context**: Wiring the ACE plugin's MCP servers (ace-gdrive, ace-ocs, ace-connect, ace-mobile) so `claude -p` subprocesses spawned by `CLIBackend` can call `mcp__plugin_ace_*` tools. Spans ace PR #73 (`.env.tpl` op-inject fix) and ace-web PR #186 (global `tsx`).
**Status**: Active — read this before touching `Dockerfile`, `docker-entrypoint.sh`, the ACE plugin's `.env.tpl`, or any new plugin that ships stdio MCP servers via `npx`.

## Problem

The ACE plugin ships four stdio MCP servers, each declared in `.claude-plugin/plugin.json` as:

```json
"ace-gdrive": {
  "command": "npx",
  "args": ["tsx", "${CLAUDE_PLUGIN_ROOT}/mcp/google-drive-server.ts"],
  "env": { "CLAUDE_PLUGIN_DATA": "${CLAUDE_PLUGIN_DATA}" }
}
```

Each server's runtime credentials (OCS/HQ/Gmail/Connect) come from a `.env`
rendered at container start by 1Password's `op inject -i .env.tpl -o ...`.

In a deployed AWS Fargate container, two distinct failure modes silently
broke the path between "Claude Code spawns the MCP" and "the MCP responds
to JSON-RPC initialize." Both presented as the same symptom:

- `init_summary.mcp_servers[]` reported `status: "failed"` (or `"pending"`
  forever)
- `claude mcp list` hung past 90s
- Chat sessions had no `mcp__plugin_ace_*` tools surfaced via ToolSearch
- `/ace:run` got into the orchestrator and then stalled with the model
  doing filesystem exploration looking for tools that never materialised

Symptom uniformity is the trap: two completely different failures look
identical at the chat layer. You only get root cause from
`~/.cache/claude-cli-nodejs/<scope>/mcp-logs-plugin-<name>/<ts>.jsonl`.

## Trap 1: `op inject` parses literal `{{ }}` and `op://` inside comments

Symptom in entrypoint logs:

```
[entrypoint] op inject FAILED — see /tmp/op-inject.err
[ERROR] parsing error at 106:30: only secret references or quoted strings
        can be enclosed in unescaped {{ }}s
[entrypoint] continuing without rendered .env; downstream ACE MCPs may
fail to find OCS/HQ/Gmail creds
```

`op inject` is **not** a comment-aware processor — it scans the file for
`{{ ... }}` blocks (Mustache-style) and `op://...` references and
validates every occurrence, including ones inside `# ...` lines. Anything
that isn't a valid secret reference or a quoted string makes the whole
inject step abort.

Two real incidents:

| When | What broke | Where |
|---|---|---|
| 2026-05-01 (commit `b07a0a5`) | A literal `op://AI-Agents/ACE - CommCareHQ` inside a comment | `.env.tpl` line ~58 |
| 2026-05-02 (ace PR #73) | A literal `{{TITLE}} / {{SUBTITLE}} / {{BODY}}` inside a comment about Slides Mustache placeholders | `.env.tpl` line 106 |

Same bug, different sigil. Both surfaced after a plugin version bump that
added the offending comment, both broke every deployed container's `.env`
render, both kept passing local dev because dev devs had the `.env`
already.

### Mitigation

1. **Don't put literal `{{ }}` or `op://` syntax inside `.env.tpl` comments.**
   Describe the format in prose; if you absolutely must show an example,
   wrap the curlies in single-quotes or split them: `'{{TITLE}}'`,
   `"op://" + path`. The comment is for humans; `op inject` doesn't read it.
2. **Verify every `.env.tpl` change with a dry inject before merging:**
   `op inject -i .env.tpl -o /tmp/test.env` from a workstation with
   `OP_SERVICE_ACCOUNT_TOKEN` set. Expected exit 0 and a populated file.
3. **The entrypoint MUST surface the error, not eat it.** `docker-entrypoint.sh`
   logs `op inject FAILED` to stdout and continues without `.env` — this is
   load-bearing for debug. Don't change it to silently skip.

## Trap 2: `npx tsx` spawns trigger an on-the-fly registry install

Symptom in `~/.cache/claude-cli-nodejs/-app/mcp-logs-plugin-ace-ace-connect/<ts>.jsonl`:

```json
{"debug":"Starting connection with timeout of 30000ms","cwd":"/app"}
{"error":"Server stderr: npm warn exec The following package was not found and will be installed: tsx@4.21.0\n..."}
{"debug":"Connection failed after 7153ms: MCP error -32000: Connection closed"}
```

The plugin declares its server as `npx tsx ${CLAUDE_PLUGIN_ROOT}/mcp/<server>.ts`.
Claude Code expands `${CLAUDE_PLUGIN_ROOT}` to the install path
(`/home/app/.claude/plugins/cache/ace/ace/<version>`) but spawns `npx`
with the **parent process's cwd**. Our parent is uvicorn at `/app`.

`npx tsx ...` resolution order:

1. `/app/node_modules/.bin/tsx` — doesn't exist
2. Parent dirs walked up to `/`: none have `node_modules/.bin/tsx`
3. `$PATH`: `tsx` not on PATH
4. Fall through: install `tsx` from the npm registry on the fly

The fall-through install takes ~7s in a warm cache. Claude Code's
MCP-connection timeout is **30 s**, but the on-the-fly install also writes
warning lines to the MCP server's stderr — and at least in observed
behaviour the connection closes before tsx is ready, with
`MCP error -32000: Connection closed`. All four ACE MCPs end up
`status=failed`.

The catch is that **one-off CLI invocations work** — `tsx`'s own
node_modules in the plugin dir resolves correctly when you exec inside
the plugin install path manually. Only the chat path, spawning from
`/app`, hits the registry-install fall-through.

### Mitigation

Install `tsx` globally in the Dockerfile so `/usr/bin/tsx` is on PATH
regardless of cwd:

```dockerfile
&& npm install -g @anthropic-ai/claude-code@latest tsx@4.21.0 \
```

Pin to the same version the plugin's `package.json` depends on so both
paths see identical behaviour. The five ACE plugin tsx-using MCPs now
resolve `tsx` instantly and complete the JSON-RPC handshake well inside
30 s.

This is a generalisable rule: **any `npx <pkg>` MCP command in a plugin
needs `<pkg>` already resolvable**. If a plugin pins a new tool (`bun`,
`deno`, `python -m something`), add it to the global install list at
build time. Alternative — set `cwd` in the spawn (`apps/common/cli_backend.py`)
to a path with the right `node_modules` — works but is fragile because
plugins pick their own `cwd`-implied dependency footprint.

## Why this is hard to debug from outside the container

- The init payload's `mcp_servers[]` array shows `failed` / `pending` but
  not why; those statuses are derived from the connection-close event
  with no error context
- `proc.stderr` from `claude -p` in `cli_backend.py` does NOT contain the
  MCP server's stderr — Claude Code captures it separately
- The actual error lives at
  `~/.cache/claude-cli-nodejs/<scope>/mcp-logs-plugin-<name>/<ts>.jsonl`
  inside the container; you have to ECS exec or ssh in to read it
- `apps/system/views.py:cli_diag` captures init payload + `tool_uses` but
  not the per-MCP log; future improvement is to also tail the most recent
  `mcp-logs-plugin-*/*.jsonl` file in the response

## Failure-domain table

| Layer | What you'll see in init | Where to look |
|---|---|---|
| `.env` not rendered → MCP boots but 401s on first cred-using call | `status: running`, but `tool_use` returns 401 / `Invalid authentication credentials` | `entrypoint` stdout + `/tmp/op-inject.err` |
| MCP fails to spawn (`tsx` missing, syntax error, missing dep) | `status: failed` | `~/.cache/claude-cli-nodejs/.../mcp-logs-plugin-<name>/<latest>.jsonl` |
| MCP spawns but never responds to initialize within 30 s | `status: pending` indefinitely | same MCP log; look for `Connection failed after Nms` |
| `${CLAUDE_PLUGIN_DATA}` not expanded by Claude Code | server's own stderr `[ace-plugin-data-dir] ... resolved_data_dir: null` | MCP log + `lib/plugin-data-dir.ts` derivation |

## Don't

- Don't paste `op://` or `{{...}}` literals into `.env.tpl` comments.
- Don't assume one MCP failing means a single root cause — the four ACE
  MCPs all use the same `npx tsx` shape, so one bug fails all four.
- Don't rely on the chat's "no MCP tools surfaced" symptom to tell you
  *why* — always pull the MCP log file.
