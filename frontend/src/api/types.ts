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

// --- ACE Opportunity Workbench types (apps/opps) ---

export interface OppCard {
  slug: string;
  display_name: string;
  labels: string[];
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
  is_gate: boolean;
  is_recurring: boolean;
  preview_text: string;
  judge: Judge | null;
  gates: Gate[];
  artifacts: Artifact[];
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
  idd_body: string;
  runs: RunSummary[];
  current_run: Run;
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

export interface CompareResult {
  opp: { slug: string; display_name: string };
  from_run: Run;
  to_run: Run;
}

export interface DiscussResponse {
  session_slug: string;
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

// Custom error class the client throws when the server returns a
// drive-token-missing 401 with a reconnect_url in the data field.
export class DriveReconnectRequired extends Error {
  reconnectUrl: string;

  constructor(reconnectUrl: string) {
    super("Google Drive access is not connected");
    this.name = "DriveReconnectRequired";
    this.reconnectUrl = reconnectUrl;
  }
}
