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

export interface SessionListPage {
  items: Session[];
  total: number;
  page: number;
  page_size: number;
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

export interface Draft {
  id: number;
  slot: "next" | "queued";
  status: "open" | "sent" | "discarded";
  body: string;
  version: number;
  last_editor: number;
  last_edit_at: string;
}

export interface Participant {
  user_id: number;
  email: string;
  display_name: string;
  role: "owner" | "editor" | "viewer";
  joined_at: string;
  last_seen_at: string | null;
}

export interface SessionState {
  messages: Message[];
  active_draft: Draft | null;
  participants: Participant[];
  presence_user_ids: number[];
  current_user_id: number;
}

// WebSocket protocol ------------------------------------------------------

export type WsAction =
  | { action: "chat.send"; data: Record<string, never> }
  | { action: "chat.stop"; data: { message_id: number } }
  | { action: "draft.update"; data: { version: number; body: string } }
  | { action: "draft.take_over"; data: Record<string, never> }
  | { action: "draft.discard"; data: Record<string, never> }
  | { action: "presence.heartbeat"; data: Record<string, never> };

export type WsEvent =
  | { event: "session.state"; data: SessionState }
  | { event: "session.error"; data: { code: string; message: string; detail?: unknown } }
  | { event: "chat.stream_start"; data: { message_id: number; turn_index: number } }
  | { event: "chat.delta"; data: { message_id: number; text: string } }
  | { event: "chat.tool_use"; data: { parent_message_id: number; tool_message_id: number; block: Record<string, unknown> } }
  | { event: "chat.tool_result"; data: { parent_message_id: number; tool_message_id: number; block: Record<string, unknown> } }
  | { event: "chat.stream_complete"; data: { message_id: number; plaintext: string } }
  | { event: "chat.stream_error"; data: { message_id: number; detail: string } }
  | { event: "chat.stream_cancelled"; data: { message_id: number; partial_len: number } }
  | { event: "draft.updated"; data: Draft }
  | { event: "draft.lock_changed"; data: { draft_id: number; holder_user_id: number | null; expires_at: number | null } }
  | { event: "draft.committed"; data: { draft_id: number; message_id: number; user_message_id: number } }
  | { event: "draft.discarded"; data: { draft_id: number } }
  | { event: "presence.joined"; data: { user_id: number; email: string; display_name: string } }
  | { event: "presence.left"; data: { user_id: number } };

export interface ApiEnvelope<T> {
  data: T | null;
  error: { code: string; message: string } | null;
}

export interface CliAuthStatus {
  authenticated: boolean;
  user: { has_blob: boolean; token_prefix: string | null };
  global: { has_blob: boolean };
}

export interface CliAuthPromoteResult {
  promoted: boolean;
  token_prefix: string;
}

// --- ACE Opportunity Workbench types (apps/opps) ---

export interface OppCard {
  slug: string;
  display_name: string;
  labels: string[];
  tags: string[];
  created_at: string | null;
  created_by: string | null;
  current_run_id: string | null;
  current_phase: string | null;
  current_step: string | null;
  status: string;
}

export interface Artifact {
  name: string;
  drive_file_id: string;
  drive_web_link: string;
  mime_type: string;
  size_bytes: number | null;
  path: string;
}

export interface Judge {
  score: number | null;
  passed: boolean | null;
  evaluated_at: string | null;
  criteria: Record<string, number>;
  rationale: string;
}

export interface Gate {
  ts: string;
  decision: "pending" | "approved" | "rejected";
  decided_by: string;
  note: string;
}

export interface Step {
  skill_name: string;
  phase: string;
  phase_display: string;
  ordinal: number;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  has_judge: boolean;
  is_recurring: boolean;
  preview_text: string;
  judge: Judge | null;
  gates: Gate[];
  artifacts: Artifact[];
}

export interface PhaseInfo {
  name: string;
  display_name: string;
  ordinal: number;
  agent: string;
}

export interface Run {
  run_id: string;
  mode: "auto" | "review" | "dry-run" | "sandbox";
  status: "running" | "blocked" | "complete" | "failed" | "abandoned";
  started_at: string | null;
  completed_at: string | null;
  current_phase: string | null;
  current_step: string | null;
  skill_versions: Record<string, string>;
  notes: string;
  steps: Step[];
}

export interface RunSummary {
  run_id: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface OppSnapshot {
  opp: OppCard;
  pdd_body: string;
  runs: RunSummary[];
  current_run: Run;
  phases: PhaseInfo[];
}

export interface StepDetail extends Step {
  primary_body: string;
}

export interface LinkedChat {
  slug: string;
  title: string;
  updated_at: string;
  owner_email: string;
}

export interface DiscussResponse {
  session_slug: string;
}

export interface Scorecard {
  latest_verdict: Judge | null;
  latest_verdict_variant: "deep" | "monitor" | "quick" | null;
  latest_scorecard_path: string | null;
  latest_scorecard_body: string;
  trend_path: string | null;
  trend_body: string;
}

export interface CreateOppPayload {
  slug: string;
  display_name: string;
  idea: string;
  mode: "auto" | "review";
}

export interface CreateOppResponse {
  slug: string;
  working_session_slug: string;
}

export interface WorkingSessionResponse {
  working_session_slug: string;
}

export interface PersonalToken {
  id: number;
  label: string;
  created_at: string;
  last_used_at: string | null;
}

export interface PersonalTokenCreated extends PersonalToken {
  raw_token: string;
}

export interface ShareTokenInfo {
  token: string;
  url: string;
  created_at: string;
}

export interface ShareTokenListItem {
  token: string;
  created_at: string;
  revoked_at: string | null;
}

export interface SharedSession {
  title: string;
  messages: SharedMessage[];
}

export interface SharedMessage {
  turn_index: number;
  role: MessageRole;
  content: Record<string, unknown>;
  plaintext: string;
  status: MessageStatus;
  created_at: string;
}
