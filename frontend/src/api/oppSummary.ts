// Public no-auth endpoint — use raw fetch so we don't pull in apiClient's
// session/CSRF middleware (which would redirect to /auth/login on auth
// errors). The public summary URL is meant to circulate as a stakeholder
// share link, with no cookies required.

import { getCsrfToken } from "@/api/csrf";
import type { Decision } from "@/api/types.ws";

/**
 * Who can actually open a link. A property of the PAYLOAD, never a
 * hostname table in this file — the URLs change every run, but the
 * access model of the system each link points into does not.
 *
 * `admin` ("admin only") means a reviewer of this run will NEVER get
 * access — it stays Dimagi-internal (ACE's shared tenants on a
 * shared-tenancy opp, the OCS team console, a link outside the opp's
 * tenancy). `reviewer` means the link is inside the opp's own tenancy:
 * `/ace:release` gives its reviewers access, so it carries NO tag
 * (Jonathan, 2026-10-03: "you should expect access"). The server derives
 * both from the opp's tenancy — `apps/opps/summary.py` § link access.
 * Gated links are still shown — tagged, not hidden.
 *
 * `unknown` (ace-web#740) is the honest answer for a Google Drive link
 * whose sharing state the server could not read. Drive tags are MEASURED
 * from the file's ACL now; they used to be asserted, and on
 * spark-facilitator/20260820-0817 that shipped a page telling an
 * external partner "Open" beside two documents that answered 401. When
 * the measurement fails, saying "public" is that bug with an extra step
 * and saying "admin" invents a wall that may not exist.
 */
export type LinkAccess = "public" | "admin" | "unknown" | "reviewer";

/**
 * A decisions-log row as the public review surface renders it — the
 * Workbench `Decision` plus the phase labelling the page groups by.
 */
export type ReviewDecision = Decision & {
  phase_label: string;
  phase_ordinal: number;
  /**
   * The plain stage name ("App build") an outside reader sees in place of
   * "Phase 3 · CommCare Setup". `null` when the run's phase tag names no
   * known stage; absent on a payload cached before it shipped.
   */
  stage_label?: string | null;
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
  /** A reviewer CONFIRMED the value in force, rather than changing it. */
  confirmed?: boolean;
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
  /**
   * "What changed because you asked" — the run's frozen claim set
   * (ace#2420).
   *
   * A CLAIM is a falsifiable statement about what THIS run's output had
   * to look like, written because a named person decided something
   * between runs. `null` on every run that authored none, which is most
   * of them, and the section then does not render at all.
   *
   * The shape mirrors `lib/render-claims.ts::renderClaimsSection` in the
   * ACE plugin — one contract, two surfaces. `verdict: null` means NO
   * VERDICT YET and must never render as met.
   */
  claims: {
    /** The tally, as `summarizeClaims` composes it: "6/8 met, 2 not met". */
    summary: string;
    total: number;
    /** TRUE only when EVERY claim is MET — a never-reached one does not pass. */
    all_met: boolean;
    counts: {
      met: number;
      unmet: number;
      not_reached: number;
      indeterminate: number;
      /** No verdict yet. A mid-run state, not a closeout one. */
      unanswered: number;
    };
    /**
     * Set when the claims file could not be read, or carried rows that
     * could not be. Rendered as a visible problem, matching
     * `classifyRunClaims`'s `ok: false` posture — never silence.
     */
    error: string | null;
    people: {
      person: string;
      claims: {
        id: string;
        claim: string;
        verdict: "MET" | "UNMET" | "NOT REACHED" | "INDETERMINATE" | null;
        /** `judged` renders as a qualifier, so it reads weaker than `probed`. */
        evidence_kind: "probed" | "judged" | null;
        /** A claim the counterpart set is marked as theirs on the page. */
        authored_by: "ace" | "counterpart";
        person: string;
        quote: string | null;
        artifact: string | null;
        checkable_at: string | null;
        /** The counterpart-facing sentence. Served to everyone. */
        says: string | null;
        /**
         * The AUDIT record — Drive file ids, MCP atom signatures,
         * read-path caveats. Served to workspace MEMBERS only; `null`
         * for everyone else, so both variants carry one shape.
         */
        evidence: string | null;
        would_settle_it: string | null;
      }[];
    }[];
  } | null;
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
  /**
   * The producing phase's own verdict on the apps above — `null` when
   * Phase 3 finished clean, so a clean run renders exactly as before.
   *
   * `spark-facilitator/20260828-0703` recorded `status: partial` with a
   * failed `entity_state_fidelity` hard gate — the PAYMENT-KEY gate —
   * and the apps section showed no status at all, rendering that run
   * identically to a clean one (ace-web#744). The page already owns the
   * honest vocabulary for this: the Phase 7 walkthrough prints "the
   * review loop stopped before it converged" rather than hiding a low
   * score. Same treatment, applied one section up.
   */
  build: {
    status: string | null;
    verdict: string | null;
    /** The run's own prose explanation, when it wrote one. */
    note: string | null;
    failing_checks: {
      name: string;
      verdict: string;
      detail: string | null;
    }[];
    /** Blockers an operator explicitly waved through, when recorded. */
    carried_blockers: {
      id: string;
      gate: string | null;
      disposition: string | null;
      residual_accepted: string | null;
    }[];
  } | null;
  /**
   * The `/ace:qa-deep` gate's verdicts — `null`, and so absent from the
   * page entirely, on every run that never took the deep gate.
   *
   * `/ace:qa-deep` writes NOTHING into `run_state.yaml` on purpose (so a
   * later `/ace:run` resume is unaffected), which means there is no
   * pointer to it anywhere in run state. The server reads the two
   * verdict FILES from Drive by path, and their presence is the only
   * honest signal that the gate ran — which gives "shows if run,
   * invisible if not" with no flag to keep in sync.
   *
   * **The gate is the headline; the score is context.** On
   * `spark-facilitator/20260828-0703` Stage A scored 8.03 against a 7.0
   * threshold and its gate is `iterate` anyway, because `--deep`
   * requires zero Fail entries and two prompts fabricated
   * safety-adjacent operational procedure. Rendering 8.03 beside a green
   * tick would tell a partner this opportunity is ready to launch. It is
   * not. Never derive an appearance of pass/fail from `score`.
   */
  deep_qa: {
    stages: {
      stage: "assistant" | "apps";
      /** What this page calls the thing that was graded. */
      label: string;
      /**
       * `/ace:qa-deep` takes `--ocs-only` / `--apps-only`, so half a
       * deep gate is a real state. A stage that did not run keeps every
       * key and nulls the values — the page SAYS it has not run rather
       * than leaving a reader to notice a shorter list.
       */
      ran: boolean;
      ran_at: string | null;
      /** `approve` | `iterate` | `reject`, or whatever the run wrote. */
      gate: string | null;
      verdict: string | null;
      score: number | null;
      threshold: number | null;
      counts: { total: number; pass: number; warn: number; fail: number };
      dimensions: { name: string; score: number | null; weight: number | null }[];
      /** The rubric's `auto_surfaced` entries, whole — severity and all. */
      findings: { severity: string | null; message: string }[];
      /** Only the entries that did NOT pass; `counts` carries the rest. */
      items: {
        ref: string;
        verdict: string;
        score: number | null;
        note: string | null;
      }[];
      /**
       * What the verdict was measured against, versus what is deployed
       * now. Phase 9 `llo-launch` refuses activation when a deep verdict
       * is missing OR STALE, so this is part of the verdict, not a
       * footnote.
       *
       * EMPTY — and `is_stale` null — whenever either side is unknown.
       * The page then shows the timestamp and leaves the judgement to
       * the reader rather than asserting freshness it cannot prove.
       */
      freshness: {
        basis: string;
        verdict_value: string;
        current_value: string;
        is_current: boolean;
      }[];
      is_stale: boolean | null;
    }[];
  } | null;
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
  /**
   * What the dashboards and the demo above are showing numbers OF.
   *
   * Phase 7 GENERATES its dataset, and until now nothing on the page
   * said so: `spark-facilitator/20260828-0703` listed two dashboards
   * built on 223 generated visit records attributed to 12 invented
   * facilitators (`labs_synthetic_opp_id: 10054`,
   * `record_counts.user_visits: 223`, `user_data: 12`,
   * `completed_works: 0`) with no qualifier at all. Named facilitators,
   * a coaching task and three planted anomalies all read as
   * observations of a real programme.
   *
   * Every field comes from the run's own `products.synthetic.source`
   * block — nothing here is hardcoded, and a run that recorded no counts
   * renders the label without them rather than inventing a figure.
   * `null` means the run generated nothing, so nothing is labelled.
   */
  synthetic: {
    is_synthetic: boolean;
    provider: string | null;
    labs_opp_id: number | null;
    visits: number | null;
    completed_works: number | null;
    cohort_size: number | null;
    cohort_population: string | null;
  } | null;
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
      /**
       * When the question has to be answered by — the ledger's
       * `blocking:` field. Read but previously discarded, which is the
       * same class of loss as an untitled row: the reader could see a
       * question and not that it gates Phase 8.
       */
      blocking: string | null;
      // The outsider fields (2026-10). Optional because a payload cached
      // before they shipped lacks them; the page falls back to the raw
      // fields above.
      /** Which run first raised it — ACE's audit trail. */
      raised_by?: string | null;
      /** `blocking` in plain words ("Before the app build stage"). */
      needed_by?: string | null;
      /** That stage has already run in this run, so the deadline passed. */
      overdue?: boolean;
      /**
       * The reviewer's question (`true`), or one Dimagi is resolving —
       * every owner is ACE / Operator / Connect team / Dimagi (`false`).
       */
      for_reviewer?: boolean;
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
    // Phases the run deliberately did not do — their sections read the
    // reason ("not part of this run …"), never "Not created".
    skipped: { phase: string; sections: string[]; reason: string }[];
    // Phases that ran without a clean verdict: one plain line, shown in
    // each section the phase produced. Empty on a clean run.
    caveats: {
      phase: string;
      sections: string[];
      verdict: string | null;
      text: string;
    }[];
    // The plain status for a run that stopped by design ("Paused — waiting
    // for an implementing organisation"), else null. Replaces "In progress"
    // in the hero. Absent on a payload cached before it shipped.
    paused?: string | null;
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
  // A released clone can take over this run's link: the API 307s to the
  // clone's summary and fetch follows it. Move the page there too, so the
  // address, and every write the page makes, is the clone's.
  const moved = resp.redirected ? forwardedSummaryPath(resp.url, base) : null;
  if (moved && moved !== window.location.pathname) {
    window.location.replace(moved + window.location.search + window.location.hash);
  }
  return (await resp.json()) as OppSummaryPayload;
}

/**
 * The summary PAGE path for a redirected summary API URL, or null when the
 * URL is not a summary API URL. `base` is the app's path prefix (e.g. `/ace`).
 */
export function forwardedSummaryPath(apiUrl: string, base: string): string | null {
  const path = new URL(apiUrl, "http://x").pathname;
  const m = path.match(/\/api\/opps\/public\/([^/]+)\/([^/]+)\/runs\/([^/]+)\/summary\/?$/);
  if (!m) return null;
  return `${base}/opps/${m[1]}/${m[2]}/runs/${m[3]}/summary`;
}

/** Raised with the server's human-readable detail when a reaction is refused. */
export class ReactionError extends Error {}

/**
 * POST one member write (edit, confirm, comment) to the summary's API.
 *
 * Members only (2026-10-03): the session cookie identifies the writer and
 * the CSRF token proves the request came from this page — the endpoints
 * are csrf_exempt at the router and refuse a member write without it. A
 * 401 (not signed in) or 403 (not a member) comes back as a
 * `ReactionError` carrying the server's sentence.
 */
async function postMemberWrite<T>(url: string, body: unknown, fallback: string): Promise<T> {
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
    let detail = fallback;
    try {
      const problem = await resp.json();
      if (typeof problem?.detail === "string" && problem.detail) detail = problem.detail;
      else if (resp.status === 422) detail = "That is too long.";
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new ReactionError(detail);
  }
  return (await resp.json()) as T;
}

function decisionUrl(workspace: string, slug: string, runId: string, decisionId: string) {
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  return (
    `${base}/api/opps/public/${encodeURIComponent(workspace)}/${encodeURIComponent(slug)}` +
    `/runs/${encodeURIComponent(runId)}/decisions/${encodeURIComponent(decisionId)}`
  );
}

/** Comment on one decision row. The commenter is the signed-in member. */
export async function postDecisionReaction(
  workspace: string,
  slug: string,
  runId: string,
  decisionId: string,
  body: { comment: string },
): Promise<DecisionReaction & { decision_id: string }> {
  return postMemberWrite(
    `${decisionUrl(workspace, slug, runId, decisionId)}/reactions`,
    body,
    "We couldn't record that. Try again in a moment.",
  );
}

/**
 * Change — or, with `confirm`, confirm — ONE decision's answer. Writes land
 * in the same store the Workbench editor writes, attributed to the
 * signed-in member.
 */
export async function postDecisionEdit(
  workspace: string,
  slug: string,
  runId: string,
  decisionId: string,
  body: {
    value: string;
    reasoning?: string;
    /** Record a CONFIRMATION of `value` (the answer in force), not a change. */
    confirm?: boolean;
  },
): Promise<PublicDecisionEdit & { decision_id: string }> {
  return postMemberWrite(
    `${decisionUrl(workspace, slug, runId, decisionId)}/edit`,
    body,
    "We couldn't record that change. Try again in a moment.",
  );
}
