// Public no-auth endpoint — use raw fetch so we don't pull in apiClient's
// session/CSRF middleware (which would redirect to /auth/login on auth
// errors). The public summary URL is meant to circulate as a stakeholder
// share link, with no cookies required.

import type { Decision } from "@/api/types.ws";

/**
 * Who can actually open a link. A property of the PAYLOAD, never a
 * hostname table in this file — the URLs change every run, but the
 * access model of the system each link points into does not. `admin`
 * means "needs an account we can't give an external partner today"
 * (CommCare HQ project membership, a Connect / OCS workspace, the
 * connect-labs OAuth login, the ace-web Workbench). Gated links are
 * still shown — tagged, not hidden.
 */
export type LinkAccess = "public" | "admin";

/**
 * A decisions-log row as the public review surface renders it — the
 * Workbench `Decision` plus the phase labelling the page groups by.
 */
export type ReviewDecision = Decision & {
  phase_label: string;
  phase_ordinal: number;
};

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
  } | null;
  // Three honest states per entry. `withheld` means the walkthrough
  // exists but failed its concept eval, so we deliberately don't put it
  // in front of a stakeholder — distinct from never having been made.
  walkthroughs: {
    persona: string;
    url: string | null;
    eval_score: number | null;
    availability: "available" | "withheld";
    withheld_reason: string | null;
    access?: LinkAccess;
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
