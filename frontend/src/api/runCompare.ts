/**
 * Compare two runs of one opp — what the later run did differently.
 *
 * GET /api/w/{workspace_slug}/opps/{slug}/compare?base=<run>&head=<run>
 *
 * Leads with what is NEW (decisions, checks) rather than score deltas: a
 * stricter grader makes the better run score lower. See
 * apps/opps/run_compare.py.
 */
import { apiClient } from "./apiClient";

export interface RunHeader {
  readonly run_id: string;
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly steps_run: number;
  readonly decision_count: number;
}

export interface CompareDecision {
  readonly id: string;
  readonly phase: string;
  readonly phase_display: string;
  readonly skill: string | null;
  readonly question: string;
  readonly answer: unknown;
  readonly overridden: boolean;
  /** Present on changed decisions only. */
  readonly before?: unknown;
  readonly after?: unknown;
}

export interface CompareStep {
  readonly skill: string;
  readonly display_name: string;
  readonly phase: string;
  readonly phase_display: string;
}

export interface StepVerdict {
  readonly label: string;
  readonly status: string;
  readonly score: number | null;
}

export interface CompareStepRow extends CompareStep {
  readonly ordinal: number | null;
  readonly base: StepVerdict | null;
  readonly head: StepVerdict | null;
  readonly changed: boolean;
}

export interface RunCompare {
  readonly schema_version: number;
  readonly opp_slug: string | null;
  readonly opp_title: string | null;
  readonly base: RunHeader;
  readonly head: RunHeader;
  readonly new_decisions: readonly CompareDecision[];
  readonly changed_decisions: readonly CompareDecision[];
  readonly dropped_decisions: readonly CompareDecision[];
  readonly new_steps: readonly CompareStep[];
  readonly dropped_steps: readonly CompareStep[];
  readonly steps: readonly CompareStepRow[];
}

export async function fetchRunCompare(
  workspaceSlug: string,
  slug: string,
  base: string,
  head: string,
): Promise<RunCompare> {
  const { data, response } = await apiClient.GET(
    "/api/w/{workspace_slug}/opps/{slug}/compare",
    {
      params: {
        path: { workspace_slug: workspaceSlug, slug },
        query: { base, head },
      },
    },
  );
  if (!response.ok) {
    throw new Error(
      response.status === 404
        ? "One of those runs couldn't be found."
        : `Couldn't compare these runs (${response.status}).`,
    );
  }
  return data as unknown as RunCompare;
}
