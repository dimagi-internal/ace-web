export type SessionStatus = "active" | "archived" | "imported";
export type BackendKind = "cli" | "api" | "mcp";
export type SessionSource = "web" | "upload";
export type MessageStatus = "pending" | "streaming" | "complete" | "error";
export type MessageRole =
  | "user"
  | "assistant"
  | "system"
  | "tool_use"
  | "tool_result";

export interface Session {
  slug: string;
  title: string;
  status: SessionStatus;
  backend_kind: BackendKind;
  source: SessionSource;
  cli_session_id: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface SessionDetail extends Session {
  messages: Message[];
}

export interface Message {
  id: number;
  turn_index: number;
  role: MessageRole;
  content: Record<string, unknown>;
  plaintext: string;
  status: MessageStatus;
  error_detail: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export type StreamEvent =
  | { type: "delta"; text: string }
  | { type: "tool_use"; block: Record<string, unknown> }
  | { type: "tool_result"; block: Record<string, unknown> }
  | { type: "session_id"; session_id: string }
  | { type: "done" }
  | { type: "error"; message: string };

export interface ApiEnvelope<T> {
  data: T | null;
  error: { code: string; message: string } | null;
}

export interface CliAuthStatus {
  authenticated: boolean;
}

export interface CliAuthStartResult {
  auth_url: string | null;
  token: string | null;
  status: "complete" | "awaiting_code";
}

export interface CliAuthPollResult {
  active: boolean;
  authenticated: boolean;
  elapsed_seconds?: number;
}
