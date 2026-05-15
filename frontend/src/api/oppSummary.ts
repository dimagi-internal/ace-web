// Public no-auth endpoint — use raw fetch so we don't pull in apiClient's
// session/CSRF middleware (which would redirect to /auth/login on auth
// errors). The public summary URL is meant to circulate as a stakeholder
// share link, with no cookies required.

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
  apps: {
    kind: "Learn" | "Deliver";
    name: string;
    nova_url: string | null;
    hq_url: string | null;
  }[];
  connect: {
    opportunity: {
      name: string;
      url: string | null;
      start_date: string | null;
      end_date: string | null;
    } | null;
    program: {
      name: string;
      url: string | null;
    } | null;
  } | null;
  training: {
    deck: { title: string; url: string } | null;
    docs: { title: string; url: string }[];
  } | null;
  assistant: {
    ocs_url: string | null;
    public_id: string;
    embed_key: string;
  } | null;
  walkthroughs: {
    persona: string;
    url: string;
    eval_score: number | null;
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
  } | null;
  open_questions: { url: string } | null;
  workbench_url: string | null;
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
