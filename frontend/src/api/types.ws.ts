/**
 * types.ws.ts — WebSocket protocol types and session detail shapes.
 *
 * These types describe the Channels WebSocket protocol (WsAction / WsEvent)
 * and the server-side session+message shapes that aren't captured as Pydantic
 * response bodies in the v2 OpenAPI schema (session detail, messages, etc.).
 *
 * All resource-layer types that ARE in generated.ts (WorkspaceOut, OppCardOut,
 * PersonalTokenOut, etc.) should be imported from generated.ts instead.
 */

// ---------------------------------------------------------------------------
// Core enum aliases — exported for backward compat with consumer files
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Session + message shapes (v2 endpoints return these but schema is opaque)
// ---------------------------------------------------------------------------

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
  preview: string;
  opp_slug: string;
  opp_run_id: string;
  opp_step_skill: string;
  opp_display_name: string;
  opp_step_skill_display: string;
}

export interface SessionDetail extends Session {
  messages: Message[];
}

export interface SessionListPage {
  items: Session[];
  total: number;
  // Legacy DRF pagination fields (used by the non-workspace path in sessions.ts).
  page: number;
  page_size: number;
  // v2 pagination fields (present when workspace-scoped path is used).
  offset?: number;
  limit?: number;
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

// ---------------------------------------------------------------------------
// WebSocket protocol
// ---------------------------------------------------------------------------

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
  | { event: "session.title_updated"; data: { title: string } }
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

// ---------------------------------------------------------------------------
// Legacy envelope (used by client.ts DRF path; not emitted by v2 endpoints)
// ---------------------------------------------------------------------------

export interface ApiEnvelope<T> {
  data: T | null;
  error: { code: string; message: string } | null;
}

// ---------------------------------------------------------------------------
// Share token shapes (v2 endpoint has opaque response)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// CLI auth shapes (v2 schema uses opaque dict for user/global sub-objects)
// ---------------------------------------------------------------------------

export interface CliAuthStatus {
  authenticated: boolean;
  user: { has_blob: boolean; token_prefix: string | null };
  global: { has_blob: boolean };
}

export interface CliAuthPromoteResult {
  promoted: boolean;
  token_prefix: string;
}

export interface NovaAuthStatus {
  connected: boolean;
  valid: boolean;
  expires_at: number | null;
  scope: string | null;
  can_manage: boolean;
}

// ---------------------------------------------------------------------------
// Opp workbench types (v2 OppSnapshot endpoint has opaque response)
// ---------------------------------------------------------------------------

export interface OppCard {
  slug: string;
  display_name: string;
  labels: string[];
  tags: string[];
  created_at: string | null;
  created_by: string | null;
  current_run_id: string | null;
  current_phase: string | null;
  current_phase_display: string | null;
  current_step: string | null;
  current_step_display: string | null;
  status: string;
  eval_score: number | null;
  eval_score_pct: number | null;
  eval_passed: boolean | null;
  last_activity_at: string | null;
  run_count: number;
  // Per-run summary populated by the workspace /opps list endpoint so the
  // OppCardRunsStrip can render phase-chip data without per-card fan-out.
  // Newest-first; empty for flat-layout opps with no runs/ subfolder.
  // See #512 — this replaced N parallel /opps/{slug}/runs calls.
  runs_summary: RunSummary[];
}

export interface Artifact {
  name: string;
  drive_file_id: string;
  drive_web_link: string;
  mime_type: string;
  size_bytes: number | null;
  path: string;
}

export type JudgeCriterionValue =
  | number
  | { score?: number; weight?: number; strength?: string; weakness?: string; [k: string]: unknown };

export interface Judge {
  score: number | null;
  score_pct: number | null;
  passed: boolean | null;
  evaluated_at: string | null;
  criteria: Record<string, JudgeCriterionValue>;
  rationale: string;
}

export interface QAFailure {
  check: string;
  type: string;
  detail: string;
  auto_fix_hint: string;
}

export interface QAResult {
  skill: string;
  target_skill: string;
  verdict: "pass" | "fail" | "incomplete";
  ran_at: string | null;
  capture_path: string | null;
  stats: { checks_run: number; checks_passed: number; checks_failed: number };
  failures: QAFailure[];
  auto_fix: { attempted: boolean | null; attempts: number | null; succeeded: boolean | null } | null;
}

export interface Step {
  skill_name: string;
  display_name: string;
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
  qa_result: QAResult | null;
  artifacts: Artifact[];
}

export interface PhaseInfo {
  name: string;
  display_name: string;
  ordinal: number;
  agent: string;
}

export interface Decision {
  id: string;
  phase: string;
  phase_raw: string;
  skill: string;
  question: string;
  ai_default: string;
  override: string;
  options_considered: string[];
  source: string;
  status: "ai-default" | "overridden";
  /** AI's rationale for the ai-default pick (read from YAML `reasoning`). */
  notes: string;
  /** Human's rationale when status=overridden (read from YAML `override_reasoning`). */
  override_reasoning: string;
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
  decisions: Decision[];
}

export interface RunSummary {
  run_id: string;
  current_phase: string | null;
  current_phase_display?: string | null;
  current_phase_ordinal?: number | null;
  current_step: string | null;
  current_step_display?: string | null;
  mode: string | null;
  last_actor: string | null;
  last_actor_at: string | null;
  lifecycle_status?: "in_progress" | "complete" | null;
  phases_total?: number;
  phases_done?: number;
  latest_phase_done?: string | null;
  latest_phase_done_display?: string | null;
  latest_phase_done_ordinal?: number | null;
}

export interface OppSnapshot {
  opp: OppCard;
  pdd_body: string;
  runs: RunSummary[];
  selected_run_id: string | null;
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
  source: SessionSource;
  kind: "step" | "opp";
  step_skill: string | null;
  step_skill_display: string | null;
  preview: string;
}

export interface DiscussResponse {
  session_slug: string;
}

export interface OppCompareSummary {
  score_a: number | null;
  passed_a: boolean | null;
  score_b: number | null;
  passed_b: boolean | null;
  score_delta: number | null;
}

export interface OppCompare {
  a: OppSnapshot;
  b: OppSnapshot;
  summary: OppCompareSummary;
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

// ---------------------------------------------------------------------------
// Cost & structure types (session-cost and session-structure endpoints have
// opaque v2 response bodies)
// ---------------------------------------------------------------------------

export interface CostTokens {
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
}

export interface CostInvocation {
  start_ts: string | null;
  wall_time_seconds: number;
  estimated_cost_usd: number;
  cost_is_partial: boolean;
  incomplete?: boolean;
  tokens: CostTokens;
}

export interface CostSkill {
  skill_name: string;
  skill_display?: string;
  invocation_count: number;
  wall_time_seconds: number;
  estimated_cost_usd: number;
  cost_is_partial: boolean;
  tokens: CostTokens;
  invocations: CostInvocation[];
}

export interface CostPhase {
  phase_name: string;
  phase_display: string;
  phase_ordinal: number;
  wall_time_seconds: number;
  estimated_cost_usd: number;
  cost_is_partial: boolean;
  tokens: CostTokens;
  skills: CostSkill[];
}

export interface CostRollupPhase {
  phase_name: string;
  phase_display: string;
  phase_ordinal: number;
  wall_time_seconds: number;
  estimated_cost_usd: number;
  cost_is_partial: boolean;
  tokens: CostTokens;
  session_slugs: string[];
}

export interface CostRollup {
  totals: CostTokens & {
    wall_time_seconds: number;
    estimated_cost_usd: number;
    cost_is_partial: boolean;
    cache_hit_ratio: number;
  };
  phases: CostRollupPhase[];
  session_count: number;
  sessions_without_breakdown: number;
}

export type StructureStatus = "ok" | "error" | "incomplete";

export interface StructureTokens {
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
}

export interface StructureToolNode {
  kind: "tool";
  tool_use_id: string;
  tool_name: string;
  label: string;
  started_at: string | null;
  wall_time_seconds: number;
  // Top-level tool rows inherit a share of the parent assistant turn's
  // cost (split evenly across parallel tools) so "where did the money go"
  // is answerable per row. Subagent-internal tools stay at 0 — their
  // cost rolls into the enclosing skill.
  estimated_cost_usd: number;
  cost_is_partial: boolean;
  status: StructureStatus;
  content_preview: string | null;
}

export interface StructureParallelGroup {
  kind: "parallel_group";
  started_at: string | null;
  wall_time_seconds: number;
  children: StructureToolNode[];
}

export interface StructureSkillNode {
  kind: "skill";
  name: string;
  display: string;
  is_subagent: boolean;
  started_at: string | null;
  wall_time_seconds: number;
  estimated_cost_usd: number;
  cost_is_partial: boolean;
  tokens: StructureTokens;
  status: StructureStatus;
  children: StructureChild[];
}

export interface StructureDirectTurnNode {
  kind: "direct_turn";
  started_at: string | null;
  model: string | null;
  estimated_cost_usd: number;
  cost_is_partial: boolean;
  tokens: StructureTokens;
  text_preview: string | null;
}

export type StructureChild =
  | StructureToolNode
  | StructureParallelGroup
  | StructureSkillNode
  | StructureDirectTurnNode;

export interface StructurePhase {
  kind: "phase";
  name: string;
  display: string;
  ordinal: number;
  wall_time_seconds: number;
  estimated_cost_usd: number;
  cost_is_partial: boolean;
  tokens: StructureTokens;
  status: StructureStatus;
  children: StructureChild[];
}

export interface StructureSession {
  wall_time_seconds: number;
  estimated_cost_usd: number;
  cost_is_partial: boolean;
  tokens: StructureTokens;
  status: StructureStatus;
}

export interface StructureTree {
  schema_version: number;
  computed_at?: string;
  session: StructureSession | null;
  phases: StructurePhase[];
  unavailable_reason?: "no-raw-jsonl" | "parse-failed";
}

// ---------------------------------------------------------------------------
// Cross-run view types
// ---------------------------------------------------------------------------

export interface PerRunSummary {
  run_id: string;
  mode: string | null;
  started_at: string | null;
  last_actor_at: string | null;
  current_phase: string | null;
  current_step: string | null;
  mean_score: number | null;
  complete_count: number;
  total_count: number;
  phase_scores: Record<
    string,
    { mean_score: number | null; complete: number; total: number }
  >;
  skill_scores: Record<string, number | null>;
  skill_passed: Record<string, boolean | null>;
  skill_status: Record<string, string>;
}

export interface SkillIndexEntry {
  skill_name: string;
  display_name: string;
  phase: string;
  phase_display: string;
  phase_ordinal: number;
  ordinal: number;
  has_judge: boolean;
}

export interface MultiRunSummary {
  per_run: PerRunSummary[];
  skill_index: SkillIndexEntry[];
}
