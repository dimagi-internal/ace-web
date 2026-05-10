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
  preview: string;
  // Opp linkage — non-empty strings when the session was launched via
  // "Discuss in chat" on a Workbench step or imported via
  // /ace:run --ace-web-url. Empty strings on plain web-native chats.
  opp_slug: string;
  opp_run_id: string;
  opp_step_skill: string;
  // Human display name resolved server-side from OppWorkspace. Empty
  // when not opp-linked or when the OppWorkspace row was deleted; UI
  // falls back to opp_slug.
  opp_display_name: string;
  // Human display name for opp_step_skill (e.g. "Idea to PDD" from
  // ``idea-to-pdd``). Empty when not step-linked; UI falls back to
  // opp_step_skill.
  opp_step_skill_display: string;
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

export interface NovaAuthStatus {
  connected: boolean;
  valid: boolean;
  expires_at: number | null;
  scope: string | null;
  can_manage: boolean;
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
  // Human label for ``current_phase`` ("Design Review" instead of
  // ``design-review``), resolved server-side from the plugin's agent
  // frontmatter. Null when ``current_phase`` is null or unknown.
  current_phase_display: string | null;
  current_step: string | null;
  // Human label for ``current_step`` ("Idea to PDD" instead of
  // ``idea-to-pdd``), resolved server-side from the plugin's SKILL.md
  // metadata. Null when ``current_step`` is null or unknown.
  current_step_display: string | null;
  status: string;
  eval_score: number | null;
  // Server-normalized 0-100. Same shape as Judge.score_pct.
  eval_score_pct: number | null;
  eval_passed: boolean | null;
  last_activity_at: string | null;
  run_count: number;
}

export interface Artifact {
  name: string;
  drive_file_id: string;
  drive_web_link: string;
  mime_type: string;
  size_bytes: number | null;
  path: string;
}

// Judge criteria entries can be a bare numeric score (legacy ``criteria``
// shape) or an object with at least ``score`` (the plugin's ``dimensions``
// shape with optional ``weight``, ``strength``, ``weakness``). Both flow
// through the API unchanged — components must handle both.
export type JudgeCriterionValue =
  | number
  | { score?: number; weight?: number; strength?: string; weakness?: string; [k: string]: unknown };

export interface Judge {
  score: number | null;
  // Server-normalized 0-100 score so the frontend never has to branch on
  // scale. Null when ``score`` is null. See ``apps/opps/serializers.py``
  // ``serialize_judge`` for the heuristic.
  score_pct: number | null;
  passed: boolean | null;
  evaluated_at: string | null;
  criteria: Record<string, JudgeCriterionValue>;
  rationale: string;
}

// Structural QA verdict on a producer artifact (added by ACE PR #146 +
// ace-web PR #249). Distinct from ``Judge``: QA is binary (pass/fail/
// incomplete) and gates eval — when QA fails, eval is skipped.
export interface QAFailure {
  check: string;
  type: string; // "static" | "llm"
  detail: string;
  auto_fix_hint: string;
}

export interface QAResult {
  skill: string;          // the QA skill that produced this (e.g. "idea-to-pdd-qa")
  target_skill: string;   // the producer skill being checked (e.g. "idea-to-pdd")
  verdict: "pass" | "fail" | "incomplete";
  ran_at: string | null;
  capture_path: string | null;
  stats: { checks_run: number; checks_passed: number; checks_failed: number };
  failures: QAFailure[];
  auto_fix: { attempted: boolean | null; attempts: number | null; succeeded: boolean | null } | null;
}

export interface Step {
  skill_name: string;
  // Human-readable name from the plugin's SKILL.md H1 (e.g. "Idea to PDD"
  // for ``idea-to-pdd``). Falls back to ``skill_name`` server-side when
  // the plugin has no display_name for this skill.
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

// One row from the per-run decisions log. Each row records a load-bearing
// default a phase skill applied. See ACE PR #160-#164 (decisions-log
// framework) and `lib/decisions-schema.ts`.
export interface Decision {
  id: string;
  // Server-projected to match `PhaseInfo.name` (e.g. "design-review")
  // so the frontend can group naively. Original tag from the YAML is
  // preserved as `phase_raw` (e.g. "1-design") for debugging.
  phase: string;
  phase_raw: string;
  skill: string;            // which skill raised the question
  question: string;
  default: string;
  options_considered: string[];
  source: string;
  status: "applied" | "overridden" | "open";
  notes: string;
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
  // Server-projected display name for ``current_phase`` (e.g. "Design Review"
  // for ``design-review``). Pulled from the plugin's agent frontmatter via
  // apps.system.reader.phase_display_names. Null when current_phase is null
  // or unknown to the registry. Same shape as OppCard.current_phase_display.
  current_phase_display?: string | null;
  // Phase ordinal (1..N) — lets the inline runs strip on /opps render
  // "P3" without having to fetch the system overview separately.
  current_phase_ordinal?: number | null;
  current_step: string | null;
  current_step_display?: string | null;
  mode: string | null;
  last_actor: string | null;
  last_actor_at: string | null;
  // Two-state lifecycle (no proactive "pause" — the plugin just stops
  // where it stops). Use the phase counts + current_phase + latest_phase_done
  // below to render the right "in progress" sub-label.
  //   "in_progress" — anything not fully complete (init, mid-step, between
  //                   phases, or halted at a HITL gate)
  //   "complete"    — every phase carries a done/complete status
  //   null          — legacy/malformed state.yaml; client falls back to
  //                   the older `!current_phase && last_actor_at` heuristic.
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
  // Human display name parallel to step_skill. Falls back to the slug
  // server-side when the skill isn't in the plugin registry; null only
  // when step_skill is null.
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

export interface CostBreakdown {
  schema_version: number;  // 0 = no data; 1 = populated
  computed_at?: string;
  totals: (CostTokens & {
    wall_time_seconds: number;
    estimated_cost_usd: number;
    cost_is_partial: boolean;
    cache_hit_ratio: number;
  }) | null;
  phases: CostPhase[];
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

// ── Cross-run views (Phase / Heatmap / Diff) ──

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

