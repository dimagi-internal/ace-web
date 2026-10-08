/**
 * Decision lineage — where each of a run's decisions came from.
 *
 * GET /api/opps/public/{ws}/{opp}/runs/{run}/lineage[?scope=opp]
 *
 * Served on the public path (the run summary renders it) and shaped per
 * viewer server-side (`apps/opps/decision_lineage.shape_for_viewer`):
 * anyone gets the chain and the per-decision origin; a signed-in member of
 * the run's workspace also gets run ids, the per-decision history, and links
 * into the workspaces they belong to. `response={200: dict}` server-side,
 * so the shape is hand-typed here.
 */

/** How a run was made from the next (older) one in the chain. */
export type LineageVia = "forked" | "seeded" | "cloned" | "";

export interface LineageStep {
  /** 0 = this run, 1 = the run it was made from, … */
  position: number;
  via: LineageVia;
  /** The phase a fork / seed re-ran from — members only ("" otherwise). */
  at_phase: string;
  /** The plain stage name of that phase ("app build"). */
  stage: string;
  /** YYYY-MM-DD, or "" when nothing dates the run. */
  date: string;
  /**
   * For a clone (`via: "cloned"`): the day it was copied into its workspace;
   * "" when unknown. Its `date` is the SOURCE's — a clone is the same run.
   */
  copied_date?: string;
  readable: boolean;
  /** Members only, and only for a workspace the viewer belongs to. */
  workbench_url: string | null;
  summary_url: string | null;
  /** Null for a non-member. */
  workspace: string | null;
  opp: string | null;
  run_id: string | null;
  decisions: number | null;
}

/**
 * - `new` — ACE decided it in THIS run;
 * - `decided` — ACE decided it in the run this one is a copy (clone) of: a
 *   clone and its source are one run, so the decision is the source's;
 * - `carried` — an earlier run decided it; it came forward unchanged;
 * - `reaffirmed` — a re-run in the same workspace decided it again, same answer;
 * - `changed` — decided differently from the run before (`on_copy`: the copy
 *   into this workspace changed it);
 * - `human` — a person set it.
 */
export type OriginKind = "new" | "decided" | "carried" | "changed" | "reaffirmed" | "human";

export interface DecisionOrigin {
  kind: OriginKind;
  /** Index into `chain` of the run the value is traced to; null when none. */
  from_position: number | null;
  /** Members only. */
  from_run: string | null;
  from_date: string;
  /**
   * Index into `chain` of the run where the value was (re)decided — 0 for
   * this run, the source's index for a clone. Absent on older payloads.
   */
  in_position?: number | null;
  /** Members only. */
  in_run?: string | null;
  in_date?: string;
  /** `changed` happened when this run was copied into its workspace. */
  on_copy?: boolean;
  /** For `changed`: the value it replaced (members only). */
  previous_value: string;
  /** For `human`: who set it (never an email for a non-member) and when. */
  by: string;
  at: string;
}

export interface DecisionHistoryEntry {
  workspace: string;
  opp: string;
  run_id: string;
  date: string;
  in_lineage: boolean;
  readable: boolean;
  found: boolean;
  /** The viewer may open this run's workspace. */
  linked: boolean;
  row_id?: string;
  /** `id` | `earlier-id` | `retired-id`. */
  match?: string;
  value?: string;
  plain_value?: string;
  status?: string;
  superseded?: boolean;
  by?: string;
  at?: string;
  reason?: string;
  /** This run's entry (not always the last: other runs may be newer). */
  current?: boolean;
  /**
   * Clones of this run folded into this entry — a clone and its source are
   * one run, so they are one entry in the history.
   */
  copied_to?: { workspace: string; date: string }[];
}

export interface DecisionLineage {
  schema_version: number;
  scope: "lineage" | "opp";
  chain: LineageStep[];
  origins: Record<string, DecisionOrigin>;
  counts: Record<OriginKind, number>;
  /** Members only; `{}` for anyone else. Oldest first, ending at this run. */
  histories: Record<string, DecisionHistoryEntry[]>;
  viewer: { is_member: boolean };
}

export async function getDecisionLineage(
  workspace: string,
  slug: string,
  runId: string,
  scope: "lineage" | "opp" = "lineage",
): Promise<DecisionLineage> {
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const q = scope === "opp" ? "?scope=opp" : "";
  const url = `${base}/api/opps/public/${encodeURIComponent(workspace)}/${encodeURIComponent(
    slug,
  )}/runs/${encodeURIComponent(runId)}/lineage${q}`;
  const resp = await fetch(url, { credentials: "same-origin" });
  if (!resp.ok) throw new Error(`getDecisionLineage: ${resp.status}`);
  return (await resp.json()) as DecisionLineage;
}
