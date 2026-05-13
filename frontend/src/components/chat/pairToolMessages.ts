import type { Message } from "../../api/types";

/**
 * A renderable row in the chat: either a single message (user / assistant /
 * standalone tool, etc.) or a paired tool_use + tool_result.
 *
 * Pairing rule: a ``tool_use`` row is paired with the FIRST subsequent
 * ``tool_result`` whose ``content.tool_use_id`` matches the ``tool_use``'s
 * ``content.id``. If no matching result exists yet (the turn is still
 * streaming), the row is rendered as a tool-pair with ``result === null``
 * — UI shows that as the "pending" state.
 *
 * Unpaired ``tool_result`` rows (no preceding ``tool_use`` with a matching
 * id — shouldn't happen in practice, but defend) fall through as standalone
 * messages so we never silently drop content.
 */
export type ChatRow =
  | { kind: "message"; message: Message; key: string }
  | { kind: "tool_pair"; use: Message; result: Message | null; key: string };

function toolUseId(message: Message): string | null {
  const content = message.content as Record<string, unknown> | undefined;
  const id = content?.id;
  return typeof id === "string" ? id : null;
}

function toolResultId(message: Message): string | null {
  const content = message.content as Record<string, unknown> | undefined;
  const id = content?.tool_use_id;
  return typeof id === "string" ? id : null;
}

export function pairToolMessages(messages: Message[]): ChatRow[] {
  const rows: ChatRow[] = [];
  // Map of tool_use_id → index into rows[] for that pair. Lets a tool_result
  // arriving later in the stream slot itself into the existing pair row.
  const pendingByToolId = new Map<string, number>();

  for (const m of messages) {
    if (m.role === "tool_use") {
      const id = toolUseId(m);
      const row: ChatRow = {
        kind: "tool_pair",
        use: m,
        result: null,
        key: `pair-${m.id}`,
      };
      rows.push(row);
      if (id !== null) {
        pendingByToolId.set(id, rows.length - 1);
      }
      continue;
    }
    if (m.role === "tool_result") {
      const id = toolResultId(m);
      if (id !== null) {
        const idx = pendingByToolId.get(id);
        if (idx !== undefined) {
          const row = rows[idx];
          if (row.kind === "tool_pair") {
            rows[idx] = { ...row, result: m };
            pendingByToolId.delete(id);
            continue;
          }
        }
      }
      // Fallthrough: no preceding tool_use match — show standalone so
      // content isn't silently dropped.
      rows.push({ kind: "message", message: m, key: `msg-${m.id}` });
      continue;
    }
    rows.push({ kind: "message", message: m, key: `msg-${m.id}` });
  }
  return rows;
}

export interface ToolCallStatus {
  kind: "success" | "error" | "pending";
  label: string;
}

/** Derive a status badge for a paired tool row. */
export function deriveToolStatus(
  use: Message,
  result: Message | null,
): ToolCallStatus {
  if (result === null) {
    return { kind: "pending", label: "running…" };
  }
  if (result.status === "error" || use.status === "error") {
    return { kind: "error", label: "error" };
  }
  // Some MCP servers signal failure in the result content rather than
  // setting an HTTP-style status — sniff for the common "Error" / "error"
  // prefixes so the badge reflects reality without server changes.
  const head = (result.plaintext || "").trim().slice(0, 80).toLowerCase();
  if (head.startsWith("error") || head.startsWith("traceback")) {
    return { kind: "error", label: "error" };
  }
  return { kind: "success", label: "ok" };
}

/** One-line summary for the collapsed tool-call header. */
export function toolPreview(use: Message, result: Message | null): string {
  const name = String(
    (use.content as { name?: unknown } | undefined)?.name ?? "tool",
  );
  // Bash → command text; everything else → first 80 chars of result body.
  const input = (use.content as { input?: Record<string, unknown> } | undefined)
    ?.input;
  if (name === "Bash" && input && typeof input.command === "string") {
    return input.command.trim().split("\n")[0]?.slice(0, 100) ?? "";
  }
  if (name === "Write" && input && typeof input.file_path === "string") {
    return input.file_path;
  }
  if (name === "Read" && input && typeof input.file_path === "string") {
    return input.file_path;
  }
  if (name === "Edit" && input && typeof input.file_path === "string") {
    return input.file_path;
  }
  if (name === "TodoWrite") {
    const todos = (input as { todos?: unknown[] } | undefined)?.todos;
    if (Array.isArray(todos)) {
      return `${todos.length} todo${todos.length === 1 ? "" : "s"}`;
    }
  }
  // Skill / Agent dispatches — show what's being dispatched.
  if (name === "Skill" && input && typeof input.skill === "string") {
    return input.skill;
  }
  if (name === "Agent") {
    const desc = (input as { description?: string } | undefined)?.description;
    if (typeof desc === "string" && desc) return desc;
    const sub = (input as { subagent_type?: string } | undefined)
      ?.subagent_type;
    if (typeof sub === "string" && sub) return sub;
  }
  // MCP tools: the post-`__` segment is the most informative part.
  if (name.startsWith("mcp__")) {
    const parts = name.split("__");
    const tail = parts[parts.length - 1] ?? name;
    return tail;
  }
  // Default: a peek at the result body so the user can scan the call
  // outcome without expanding every row.
  return (result?.plaintext || "").split("\n")[0]?.slice(0, 100) ?? "";
}

/** Short display label for the tool name in the collapsed header. */
export function toolDisplayName(use: Message): string {
  const name = String(
    (use.content as { name?: unknown } | undefined)?.name ?? "tool",
  );
  if (name.startsWith("mcp__")) {
    // mcp__plugin_ace_ace-gdrive__drive_create_file → "drive_create_file"
    const parts = name.split("__");
    return parts[parts.length - 1] ?? name;
  }
  return name;
}
