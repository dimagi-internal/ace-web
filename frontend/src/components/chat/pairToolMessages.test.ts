import { describe, expect, it } from "vitest";

import type { Message } from "../../api/types";
import {
  deriveToolStatus,
  pairToolMessages,
  toolDisplayName,
  toolPreview,
} from "./pairToolMessages";

function msg(partial: Partial<Message> & { id: number; role: Message["role"] }): Message {
  return {
    id: partial.id,
    turn_index: partial.id,
    role: partial.role,
    content: {},
    plaintext: "",
    status: "complete",
    error_detail: null,
    started_at: null,
    completed_at: null,
    created_at: "2026-05-13T00:00:00Z",
    ...partial,
  };
}

describe("pairToolMessages", () => {
  it("pairs consecutive tool_use + tool_result by id/tool_use_id", () => {
    const rows = pairToolMessages([
      msg({ id: 1, role: "user", plaintext: "hi" }),
      msg({
        id: 2,
        role: "tool_use",
        content: { id: "t1", name: "Bash", input: { command: "ls" } },
      }),
      msg({
        id: 3,
        role: "tool_result",
        content: { tool_use_id: "t1" },
        plaintext: "out",
      }),
      msg({ id: 4, role: "assistant", plaintext: "done" }),
    ]);
    expect(rows).toHaveLength(3);
    expect(rows[0].kind).toBe("message");
    expect(rows[1].kind).toBe("tool_pair");
    if (rows[1].kind === "tool_pair") {
      expect(rows[1].use.id).toBe(2);
      expect(rows[1].result?.id).toBe(3);
    }
    expect(rows[2].kind).toBe("message");
  });

  it("pairs tool_use with later non-adjacent tool_result", () => {
    const rows = pairToolMessages([
      msg({ id: 1, role: "tool_use", content: { id: "a", name: "X" } }),
      msg({ id: 2, role: "tool_use", content: { id: "b", name: "Y" } }),
      msg({ id: 3, role: "tool_result", content: { tool_use_id: "a" } }),
      msg({ id: 4, role: "tool_result", content: { tool_use_id: "b" } }),
    ]);
    expect(rows).toHaveLength(2);
    expect(rows[0].kind).toBe("tool_pair");
    expect(rows[1].kind).toBe("tool_pair");
    if (rows[0].kind === "tool_pair" && rows[1].kind === "tool_pair") {
      expect(rows[0].use.id).toBe(1);
      expect(rows[0].result?.id).toBe(3);
      expect(rows[1].use.id).toBe(2);
      expect(rows[1].result?.id).toBe(4);
    }
  });

  it("leaves an in-flight tool_use with null result so UI can show pending", () => {
    const rows = pairToolMessages([
      msg({ id: 1, role: "tool_use", content: { id: "t1", name: "Bash" } }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].kind).toBe("tool_pair");
    if (rows[0].kind === "tool_pair") {
      expect(rows[0].result).toBeNull();
    }
  });

  it("falls back to standalone when a tool_result has no matching use", () => {
    const rows = pairToolMessages([
      msg({ id: 1, role: "tool_result", content: { tool_use_id: "ghost" } }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].kind).toBe("message");
  });

  it("doesn't lose tool calls in long sessions (the Leep regression)", () => {
    // Pattern observed in Leep: ~88 messages with ~44 tool_use rows alternating
    // with ~42 tool_results. The audit found that pre-refactor every tool_use
    // and every tool_result rendered as its own collapsible row (86 rows after
    // the initial assistant message) — the pairing collapses to 44 pairs.
    const msgs: Message[] = [];
    for (let i = 0; i < 44; i++) {
      msgs.push(msg({
        id: i * 2 + 1,
        role: "tool_use",
        content: { id: `t${i}`, name: "Bash" },
      }));
      if (i < 42) {
        msgs.push(msg({
          id: i * 2 + 2,
          role: "tool_result",
          content: { tool_use_id: `t${i}` },
        }));
      }
    }
    const rows = pairToolMessages(msgs);
    expect(rows).toHaveLength(44);
    expect(rows.filter((r) => r.kind === "tool_pair")).toHaveLength(44);
    // First 42 paired, last 2 pending.
    const pending = rows.filter(
      (r) => r.kind === "tool_pair" && r.result === null,
    );
    expect(pending).toHaveLength(2);
  });
});

describe("deriveToolStatus", () => {
  it("returns pending when result is missing", () => {
    const use = msg({ id: 1, role: "tool_use" });
    expect(deriveToolStatus(use, null).kind).toBe("pending");
  });

  it("returns error when result is in error status", () => {
    const use = msg({ id: 1, role: "tool_use" });
    const result = msg({ id: 2, role: "tool_result", status: "error" });
    expect(deriveToolStatus(use, result).kind).toBe("error");
  });

  it("sniffs error-like result content", () => {
    const use = msg({ id: 1, role: "tool_use" });
    const result = msg({
      id: 2,
      role: "tool_result",
      plaintext: "Error: file not found",
    });
    expect(deriveToolStatus(use, result).kind).toBe("error");
  });

  it("returns success on a clean result", () => {
    const use = msg({ id: 1, role: "tool_use" });
    const result = msg({ id: 2, role: "tool_result", plaintext: "ok" });
    expect(deriveToolStatus(use, result).kind).toBe("success");
  });
});

describe("toolPreview", () => {
  it("shows the first line of a Bash command", () => {
    const use = msg({
      id: 1,
      role: "tool_use",
      content: {
        name: "Bash",
        input: { command: "ls -la /tmp\n# more after newline" },
      },
    });
    expect(toolPreview(use, null)).toBe("ls -la /tmp");
  });

  it("shows file_path for Read/Write/Edit", () => {
    for (const name of ["Read", "Write", "Edit"]) {
      const use = msg({
        id: 1,
        role: "tool_use",
        content: { name, input: { file_path: "/a/b.txt" } },
      });
      expect(toolPreview(use, null)).toBe("/a/b.txt");
    }
  });

  it("shows todo count for TodoWrite", () => {
    const use = msg({
      id: 1,
      role: "tool_use",
      content: {
        name: "TodoWrite",
        input: { todos: [{}, {}, {}] },
      },
    });
    expect(toolPreview(use, null)).toBe("3 todos");
  });

  it("shows the skill name for Skill", () => {
    const use = msg({
      id: 1,
      role: "tool_use",
      content: { name: "Skill", input: { skill: "ace:run" } },
    });
    expect(toolPreview(use, null)).toBe("ace:run");
  });

  it("strips the mcp prefix for MCP tools", () => {
    const use = msg({
      id: 1,
      role: "tool_use",
      content: {
        name: "mcp__plugin_ace_ace-gdrive__drive_create_file",
        input: {},
      },
    });
    expect(toolDisplayName(use)).toBe("drive_create_file");
  });
});
