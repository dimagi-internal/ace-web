/**
 * Reviewer feedback — what an outside expert said about an opp, and what it
 * changed.
 *
 * GET /api/w/{workspace_slug}/opps/{slug}/feedback
 *
 * Opp-level, not per-run: a review is written against one run but survives
 * every later one, which is the point — the ledger is how you see that an
 * outsider's comment changed the system.
 */
import { apiClient } from "./apiClient";

export interface FeedbackItem {
  readonly id: string;
  /** The section the comment was left against. */
  readonly anchor: string;
  /** The reviewer's own words, unedited. */
  readonly verbatim: string;
}

/** Counts READ from the plugin's rendered ledger line, never recomputed here —
 *  they come from a GitHub join ace-web deliberately doesn't reimplement.
 *  Null when that line isn't present. */
export interface FeedbackTally {
  readonly comments: number;
  readonly shipped: number;
  readonly needs_human: number;
  readonly unrouted: number;
}

export interface FeedbackRecord {
  readonly slug: string;
  readonly reviewer: string;
  readonly reviewer_email: string;
  readonly received_at: string;
  readonly channel: string;
  readonly artifact: string;
  readonly artifact_url: string;
  readonly against_run: string;
  /** The run that acted on the review. READ from the rendered ledger (the
   *  inbound record predates the response); empty when not stated. */
  readonly responding_run: string;
  readonly items: readonly FeedbackItem[];
  readonly item_count: number;
  readonly tally: FeedbackTally | null;
  /** The plugin's derived "where did my comment go" view, as markdown. Empty
   *  when the review has landed but the ledger hasn't been rendered yet. */
  readonly ledger_body: string;
  readonly ledger_url: string;
  readonly record_url: string;
}

export interface FeedbackPayload {
  readonly schema_version: number;
  readonly records: readonly FeedbackRecord[];
}

export async function fetchFeedback(
  workspaceSlug: string,
  slug: string,
): Promise<FeedbackPayload> {
  const { data, response } = await apiClient.GET(
    "/api/w/{workspace_slug}/opps/{slug}/feedback",
    { params: { path: { workspace_slug: workspaceSlug, slug } } },
  );
  if (!response.ok) {
    throw new Error(`Couldn't load this opp's reviews (${response.status}).`);
  }
  return data as unknown as FeedbackPayload;
}
