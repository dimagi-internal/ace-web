/**
 * Run replay API client.
 *
 * GET /api/w/{workspace_slug}/opps/{slug}/runs/{run_id}/replay
 *
 * The response is `response={200: dict}` server-side (it nests the legacy
 * serialize_opp_* step/judge/decision shapes, which a thin Pydantic schema
 * would silently drop fields from), so the generated types carry no body and
 * we hand-type it here.
 *
 * Spec: docs/specs/2026-09-17-ace-demo-player-design.md
 */
import { apiClient } from "./apiClient";

/** How a run's clock was established.
 *
 * - `measured` — steps carry their own timestamps. Step times are real.
 * - `phase`    — only phase boundaries are stamped (what a real run actually
 *   records). The run clock and the per-phase ledger are real; step offsets
 *   are interpolated for layout and carry `t_estimated`, so the player must
 *   not print them as step times.
 * - `ordinal`  — nothing is stamped. Sequence only, no clock anywhere.
 */
export type TimingSource = "measured" | "phase" | "ordinal";

export type ReplayActId = "timeline" | "time_ledger" | "gates" | "decisions";

export interface DemoArtifact {
  readonly name: string | null;
  readonly url: string | null;
}

export interface DemoJudge {
  readonly score?: number | null;
  /** Server-normalised 0-100. The Workbench prefers this over `score`. */
  readonly score_pct?: number | null;
  readonly passed?: boolean | null;
  readonly rationale?: string | null;
  readonly criteria?: Record<string, unknown> | null;
}

export interface DemoQaResult {
  readonly verdict?: string | null;
  readonly passed?: boolean | null;
  readonly failures?: readonly unknown[] | null;
  readonly checks_run?: number | null;
  readonly checks_failed?: number | null;
}

export interface DemoEvent {
  readonly seq: number;
  /** Seconds from the run origin, or null when nothing places this event. */
  readonly t: number | null;
  /** True when `t` was interpolated across the phase for layout rather than
   *  measured. Never render an estimated `t` as a time. */
  readonly t_estimated?: boolean;
  readonly kind: "phase_start" | "step_start" | "step_end";
  readonly phase: string;
  readonly phase_display: string;
  readonly skill?: string | null;
  readonly skill_display?: string | null;
  readonly status?: string | null;
  readonly preview_text?: string | null;
  readonly duration_seconds?: number | null;
  readonly artifacts?: readonly DemoArtifact[];
  readonly judge?: DemoJudge | null;
  readonly qa_result?: DemoQaResult | null;
  readonly error?: string | null;
}

/** One skill in the run's plan, ran or not. */
export interface LadderStep {
  readonly skill: string;
  readonly skill_display: string;
  readonly ordinal: number | null;
  readonly status: string | null;
  /** False for a step that never ran — shown greyed so the audience can see
   *  what was still ahead, rather than steps appearing from nowhere. */
  readonly ran: boolean;
  readonly has_judge?: boolean | null;
  readonly judge: DemoJudge | null;
  readonly qa_result: DemoQaResult | null;
  readonly preview_text?: string | null;
  readonly error?: string | null;
  readonly artifacts: readonly DemoArtifact[];
}

export interface LadderPhase {
  readonly phase: string;
  readonly phase_display: string;
  readonly ordinal: number | null;
  readonly steps: readonly LadderStep[];
}

export interface DemoTimeline {
  readonly timing_source: TimingSource;
  readonly origin: string | null;
  readonly wall_seconds: number | null;
  readonly events: readonly DemoEvent[];
  /** The run's whole plan, phase by phase. */
  readonly ladder: readonly LadderPhase[];
}

export interface LedgerSkill {
  readonly skill: string | null;
  readonly skill_display: string | null;
  readonly status: string | null;
  readonly seconds: number | null;
}

export interface LedgerPhase {
  readonly phase: string;
  readonly phase_display: string;
  /** Measured span: first start to last completion. Includes the gaps. */
  readonly seconds: number | null;
  /** Summed skill durations. Excludes the gaps. */
  readonly active_seconds: number | null;
  readonly skill_count: number;
  readonly skills: readonly LedgerSkill[];
}

export interface DemoLedger {
  readonly wall_seconds: number | null;
  readonly timing_source: TimingSource;
  readonly phases: readonly LedgerPhase[];
}

export interface DemoGate {
  readonly skill: string | null;
  readonly skill_display: string | null;
  readonly phase: string | null;
  readonly phase_display: string | null;
  readonly ordinal: number | null;
  readonly status: string;
  readonly judge: DemoJudge | null;
  readonly qa_result: DemoQaResult | null;
  readonly error: string | null;
}

export interface DemoDecisionRow {
  readonly row_id?: string;
  readonly question?: string;
  readonly ai_default?: string;
  readonly override?: string | null;
  readonly status?: string;
  readonly phase?: string;
  readonly notes?: string;
  readonly override_reasoning?: string | null;
}

export interface DemoDecisions {
  readonly total: number;
  readonly overridden_count: number;
  readonly rows: readonly DemoDecisionRow[];
}

export type ReplayActData = DemoTimeline | DemoLedger | { gates: readonly DemoGate[] } | DemoDecisions;

export interface ReplayAct {
  readonly id: ReplayActId;
  readonly title: string;
  readonly available: boolean;
  /** Present whenever `available` is false — the player says why rather than
   *  rendering an empty act. */
  readonly unavailable_reason: string | null;
  readonly data: ReplayActData;
}

export interface DemoRunHeader {
  readonly opp_slug: string | null;
  readonly opp_title: string | null;
  readonly run_id: string | null;
  readonly status: string | null;
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly wall_seconds: number | null;
  readonly step_count: number;
}

export interface ReplayPayload {
  readonly schema_version: number;
  readonly run: DemoRunHeader;
  readonly timing_source: TimingSource;
  readonly capabilities: Readonly<Record<ReplayActId, boolean>>;
  readonly acts: readonly ReplayAct[];
}

export async function fetchReplay(
  workspaceSlug: string,
  slug: string,
  runId: string,
): Promise<ReplayPayload> {
  const { data, response } = await apiClient.GET(
    "/api/w/{workspace_slug}/opps/{slug}/runs/{run_id}/replay",
    {
      params: {
        path: { workspace_slug: workspaceSlug, slug, run_id: runId },
      },
    },
  );
  if (!response.ok) {
    throw new Error(`Couldn't load this run (${response.status}).`);
  }
  return data as unknown as ReplayPayload;
}

/** Pull one act out of a payload, typed. Returns null when the run can't
 *  support it — callers render the reason, not an empty stage. */
export function actOf(payload: ReplayPayload, id: ReplayActId): ReplayAct | null {
  return payload.acts.find((a) => a.id === id) ?? null;
}

/** The timeline act's data, or null when this run can't be replayed. */
export function timelineOf(payload: ReplayPayload): DemoTimeline | null {
  const act = actOf(payload, "timeline");
  return act?.available ? (act.data as DemoTimeline) : null;
}
