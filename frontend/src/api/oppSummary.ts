import { apiFetch } from "./client";

// Matches apps/opps/summary.py build_summary_payload return shape.
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
  open_questions: { url: string } | null;
  workbench_url: string | null;
}

export function getPublicOppSummary(
  workspace: string,
  slug: string,
  runId: string,
): Promise<OppSummaryPayload> {
  return apiFetch<OppSummaryPayload>(
    `/api/opps/public/${encodeURIComponent(workspace)}/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}/summary`,
  );
}
