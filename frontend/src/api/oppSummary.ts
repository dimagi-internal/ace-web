// Public no-auth endpoint — use raw fetch so we don't pull in apiClient's
// session/CSRF middleware (which would redirect to /auth/login on auth
// errors). The public summary URL is meant to circulate as a stakeholder
// share link, with no cookies required.

import { getCsrfToken } from "@/api/csrf";
import type { Decision } from "@/api/types.ws";

/**
 * Who can actually open a link. A property of the PAYLOAD, never a
 * hostname table in this file — the URLs change every run, but the
 * access model of the system each link points into does not. `admin`
 * means "needs an account we can't give an external partner today"
 * (CommCare HQ project membership, a Connect / OCS workspace, the
 * connect-labs OAuth login, the ace-web Workbench). Gated links are
 * still shown — tagged, not hidden.
 *
 * `unknown` (ace-web#740) is the honest answer for a Google Drive link
 * whose sharing state the server could not read. Drive tags are MEASURED
 * from the file's ACL now; they used to be asserted, and on
 * spark-facilitator/20260820-0817 that shipped a page telling an
 * external partner "Open" beside two documents that answered 401. When
 * the measurement fails, saying "public" is that bug with an extra step
 * and saying "admin" invents a wall that may not exist.
 */
export type LinkAccess = "public" | "admin" | "unknown";

/**
 * A decisions-log row as the public review surface renders it — the
 * Workbench `Decision` plus the phase labelling the page groups by.
 */
export type ReviewDecision = Decision & {
  phase_label: string;
  phase_ordinal: number;
};

/**
 * One partner reaction to one decision row. `feedback_ref` is the
 * `<record-slug>/<item-id>` provenance stamp every downstream change
 * cites (`Feedback-Ref:` on an issue, `feedback_ref:` on a decisions
 * row) — it is what lets a reviewer see where their comment went.
 * Reviewer emails are deliberately not served on the public payload.
 */
/**
 * One superseded state of a decision row, newest first in `history`.
 * Emails are never projected publicly; the NAME always is — attribution
 * is the safety mechanism behind letting anyone edit, so hiding it would
 * defeat the model.
 */
export interface DecisionEditEntry {
  override: string;
  reasoning: string;
  decided_by_name: string;
  decided_by_verified: boolean;
  decided_at: string;
}

/**
 * A decision's current human-set answer.
 *
 * Read out of the SAME `<opp>/inputs/decision-overrides.yaml` the
 * Workbench's authenticated editor writes and the ACE plugin binds on the
 * next run — not a public-only shadow store. `decisions.rows` is what the
 * RUN decided; this is what humans have changed since.
 *
 * `is_revert` marks a row restored to the AI default: inert for the next
 * run, but kept (with its history) so "someone reverted this" stays
 * visible rather than being erased.
 */
export interface PublicDecisionEdit extends DecisionEditEntry {
  source_run_id: string;
  is_revert: boolean;
  history: DecisionEditEntry[];
}

export interface DecisionReaction {
  reviewer: string;
  comment: string;
  received_at: string;
  feedback_ref: string;
}

// Matches apps/opps/summary.py build_summary_payload return shape.
// Backed by phases.<phase>.products.* blocks in run_state.yaml as of
// plugin v0.13.155-v0.13.172 state-consolidation.
export interface OppSummaryPayload {
  opp: {
    workspace_slug: string;
    slug: string;
    run_id: string;
    display_name: string;
    description: string;
    status: "active" | "closed" | "in_progress";
    end_date: string | null;
  };
  // The PDD (and Work Order when present) — what a reviewer actually
  // comments on. Absent before: the page linked the training pack but not
  // the design it came from.
  design: {
    docs: { title: string; url: string; access: LinkAccess }[];
  } | null;
  apps: {
    kind: "Learn" | "Deliver";
    name: string;
    // nova_url is intentionally not surfaced — the Nova build tool has no
    // valid public URL. hq_url is the stakeholder-facing app link.
    hq_url: string | null;
    access: LinkAccess;
  }[];
  connect: {
    // Only the opportunity is surfaced — the program URL 404s publicly.
    opportunity: {
      name: string;
      url: string | null;
      start_date: string | null;
      end_date: string | null;
      access: LinkAccess;
    };
  } | null;
  training: {
    deck: { title: string; url: string; access: LinkAccess } | null;
    docs: { title: string; url: string; access: LinkAccess }[];
  } | null;
  assistant: {
    ocs_url: string | null;
    /** Access of `ocs_url` — the console. The chat widget is public. */
    access: LinkAccess;
    public_id: string;
    embed_key: string;
    /**
     * What the run recorded the assistant as actually indexing. EMPTY on
     * every run that recorded nothing, which is most of them today — and
     * the page must then say nothing about what the bot knows.
     *
     * The page used to carry a constant: "Trained on the design doc,
     * training pack, and app guides for this opportunity." It was
     * derived from nothing. On spark-facilitator/20260820-0817 the opp
     * collection held 16 files and none of the five training-pack
     * documents the same page links were among them. ACE shipped
     * `ocs-knowledge-refresh` (ace#1715) so later runs do index them —
     * which is exactly why this has to be data: the claim is true for
     * some runs and false for others.
     */
    knowledge_sources: string[];
  } | null;
  // Four honest states per entry. `withheld` means the walkthrough
  // exists but failed its concept eval, so we deliberately don't put it
  // in front of a stakeholder — distinct from never having been made.
  // `unavailable` means it exists and was not withheld, but no URL came
  // through in a shape the summary reader recognises; it is surfaced
  // rather than dropped so a produced artifact never reads as absent
  // (ace#1432). Both render through the same no-link branch.
  walkthroughs: {
    persona: string;
    url: string | null;
    /**
     * The canopy DDD concept rubric is anchored 1–5
     * (`skills/ddd-concept-eval/rubric.yaml`, anchors "5"…"1"), NOT
     * 1–10. The page rendered `{score}/10` until ace-web#740, so the
     * audited run's concept 2.0 — 2 out of 5 — read as 2 out of 10,
     * roughly half as good as it actually was.
     */
    eval_score: number | null;
    availability: "available" | "withheld" | "unavailable";
    withheld_reason: string | null;
    access?: LinkAccess;
    /**
     * The DDD loop's own record of whether the score means anything.
     * Every field independently nullable — a run that recorded none of
     * them must render as before, with no invented reassurance.
     *
     * `terminal_status` is FOUR-VALUED on purpose
     * (`converged_clean` / `converged_with_open_questions` /
     * `stopped_not_converged` / `diverging`) and must never be collapsed
     * to pass/fail: "converged, good" and "converged, still failing"
     * cannot render identically. An unrecognised value is passed through
     * verbatim rather than dropped.
     *
     * `measures_pre_fix_artifact` is a HARD caveat, not a footnote: it
     * says the score AND the linked video measure an artifact that has
     * since been fixed. Presenting either bare is the specific failure
     * this field exists to prevent.
     */
    ddd: {
      terminal_status: string | null;
      iterations_completed: number | null;
      measures_pre_fix_artifact: boolean;
      note: string | null;
    };
  }[];
  dashboards: {
    title: string;
    url: string;
    access: LinkAccess;
  }[];
  selected_llo: {
    org_slug: string;
    org_display_name: string;
    contact_email: string | null;
    awarded_at: string | null;
  } | null;
  solicitation: {
    url: string;
    deadline: string | null;
    status: string | null;
    access: LinkAccess;
  } | null;
  launch: {
    went_live_at: string;
    llo_org_display_name: string | null;
  } | null;
  cycle_grade: {
    letter: string;
    headline: string;
    overall_score: number | null;
  } | null;
  opp_eval: {
    overall_score: number;
    verdict: string | null;
    mode: string | null;
  } | null;
  learnings: {
    summary_url: string;
    new_pdd_url: string | null;
    iteration_warranted: boolean;
    access: LinkAccess;
  } | null;
  // "What we could not decide" — content, not just a link: the doc is an
  // internal working artifact nobody shares, so a bare link is useless to
  // the partner it is written for.
  open_questions: {
    url: string | null;
    access: LinkAccess;
    items: {
      title: string;
      detail: string;
      owner: string | null;
      answered_in: string | null;
    }[];
  } | null;
  /**
   * Reactions this run has collected from partners, keyed by decision id.
   * A comment nobody can find later is theatre — these are read back out
   * of the same feedback records `skills/feedback-ledger` consumes, so
   * what a partner writes here reaches the next run's ledger.
   */
  reactions: {
    total: number;
    by_decision: Record<string, DecisionReaction[]>;
  };
  /**
   * Human-set answers keyed by decision id. Anyone with this link can
   * change one in place; every change here carries who made it, when,
   * and every value it replaced.
   */
  decision_edits: Record<string, PublicDecisionEdit>;
  // "What we decided and why" — the run's decisions log, the same rows
  // the Workbench renders, stripped to a read/react surface.
  decisions: {
    total: number;
    counts: {
      stated: number;
      inferred: number;
      conflicting: number;
      overridden: number;
    };
    rows: ReviewDecision[];
  } | null;
  // How far the run got, and which sections that makes premature. A run
  // paused at the Phase 8→9 boundary has no LLO / launch / score by
  // design — those read "not started", not "missing".
  stage: {
    label: string | null;
    pending_sections: string[];
  } | null;
  // Rendered reviewer feedback ledgers ("where did my comment go?"), one
  // stable doc per review event. Newest first.
  feedback: { title: string; url: string; access: LinkAccess }[];
  // Shown to everyone, tagged `admin only` for non-members. Hiding a
  // link an external reviewer can't use is the same failure as letting
  // it 404 on them, just quieter.
  workbench: { url: string; access: LinkAccess } | null;
  // Decides only whether the page DRAWS the access tags — a member
  // already knows which links are internal, so the tag is noise there.
  viewer: { is_member: boolean };
}

export async function getPublicOppSummary(
  workspace: string,
  slug: string,
  runId: string,
): Promise<OppSummaryPayload> {
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const url = `${base}/api/opps/public/${encodeURIComponent(workspace)}/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}/summary`;
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`getPublicOppSummary: ${resp.status}`);
  }
  return (await resp.json()) as OppSummaryPayload;
}

/** Raised with the server's human-readable detail when a reaction is refused. */
export class ReactionError extends Error {}

/**
 * Submit one reaction against one decision row.
 *
 * Public endpoint, same no-auth posture as the summary read: the page a
 * partner is handed has no login and they cannot self-serve one. The
 * reviewer name is required and self-reported — see
 * `apps/opps/reactions.py` for why anonymous was not an option.
 */
export async function postDecisionReaction(
  workspace: string,
  slug: string,
  runId: string,
  decisionId: string,
  body: { reviewer: string; reviewer_email?: string; comment: string },
): Promise<DecisionReaction & { decision_id: string }> {
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const url =
    `${base}/api/opps/public/${encodeURIComponent(workspace)}/${encodeURIComponent(slug)}` +
    `/runs/${encodeURIComponent(runId)}/decisions/${encodeURIComponent(decisionId)}/reactions`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = "We couldn't record that. Try again in a moment.";
    try {
      const problem = await resp.json();
      if (typeof problem?.detail === "string" && problem.detail) detail = problem.detail;
      else if (resp.status === 422) detail = "That comment is too long.";
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new ReactionError(detail);
  }
  return (await resp.json()) as DecisionReaction & { decision_id: string };
}


/**
 * Change ONE decision's answer.
 *
 * Deliberately not member-gated and deliberately without a proposal
 * state: reviewer 2 changing reviewer 1's answer, and Dimagi changing
 * either, are the same act (Jonathan, 2026-08-14). The bar to start
 * engaging with ACE has to be very low because it is speculative AI
 * work — an account requirement is a barrier, a name field is not.
 *
 * `reviewer` is required only for an anonymous caller; the server
 * ignores it for a signed-in one (logged in ⇒ never anonymous). Writes
 * land in the same store the Workbench editor writes.
 */
export async function postDecisionEdit(
  workspace: string,
  slug: string,
  runId: string,
  decisionId: string,
  body: {
    value: string;
    reasoning?: string;
    reviewer?: string;
    reviewer_email?: string;
  },
): Promise<PublicDecisionEdit & { decision_id: string }> {
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const url =
    `${base}/api/opps/public/${encodeURIComponent(workspace)}/${encodeURIComponent(slug)}` +
    `/runs/${encodeURIComponent(runId)}/decisions/${encodeURIComponent(decisionId)}/edit`;
  // The CSRF token is what lets the server ATTRIBUTE the change to a
  // signed-in member rather than treating them as anonymous — the
  // endpoint is csrf_exempt because it must accept a genuinely anonymous
  // POST, so a token is how a session identity earns trust. Absent (a
  // partner with no account) it is simply omitted and the name they typed
  // is used instead.
  const csrf = getCsrfToken();
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRFToken": csrf } : {}),
    },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = "We couldn't record that change. Try again in a moment.";
    try {
      const problem = await resp.json();
      if (typeof problem?.detail === "string" && problem.detail) detail = problem.detail;
      else if (resp.status === 422) detail = "That answer is too long.";
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new ReactionError(detail);
  }
  return (await resp.json()) as PublicDecisionEdit & { decision_id: string };
}
