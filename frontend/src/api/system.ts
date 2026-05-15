import { apiClient } from "./apiClient";
import type { components } from "./generated";
import type { AgentDetail, SkillDetail, SystemSnapshot } from "../components/system/types";

type SystemOverviewOut = components["schemas"]["SystemOverviewOut"];
type SkillDetailOut = components["schemas"]["SkillDetailOut"];
type AgentDetailOut = components["schemas"]["AgentDetailOut"];

/**
 * Map a SystemOverviewOut (v2 Pydantic schema) to the SystemSnapshot shape
 * expected by the System Overview UI components.
 */
function mapOverview(out: SystemOverviewOut): SystemSnapshot {
  return {
    plugin_version: out.plugin_version ?? null,
    remote_version: out.remote_version ?? null,
    update_available: out.update_available ?? null,
    warning: out.warning ?? null,
    skills: out.skills.map((s) => ({
      name: s.name,
      display_name: s.display_name,
      description: s.description,
      ordinal: s.ordinal ?? null,
      phase: s.phase ?? null,
      has_judge: s.has_judge,
      is_recurring: s.is_recurring,
      primary_output: s.primary_output ?? null,
      artifacts_produced: s.artifacts_produced.map((a) => ({
        path: a.path,
        description: a.description,
        required: a.required,
      })),
      artifacts_consumed: s.artifacts_consumed.map((a) => ({
        path: a.path,
        description: a.description,
        required: a.required,
      })),
    })),
    agents: out.agents.map((a) => ({
      name: a.name,
      description: a.description,
      model: a.model,
    })),
    artifacts: out.artifacts.map((a) => ({
      path: a.path,
      description: a.description,
      required: a.required,
      produced_by: a.produced_by ?? "",
      consumed_by: [...a.consumed_by],
      // v2 ArtifactOut has no phase field — leave empty
      phase: "",
    })),
    phases: out.phases.map((p) => ({
      name: p.name,
      display_name: p.display_name,
      ordinal: p.ordinal,
      agent: p.agent,
    })),
    mcps: out.mcps.map((m) => ({
      name: m.name,
      source_file: m.source_file ?? null,
      warning: m.warning ?? null,
      tools: m.tools.map((t) => ({
        name: t.name,
        description: t.description || null,
        params: [],
        used_by: [...t.used_by],
        line: 0,
      })),
    })),
  };
}

function mapSkillDetail(out: SkillDetailOut): SkillDetail {
  return {
    name: out.name,
    display_name: out.display_name,
    description: out.description,
    ordinal: out.ordinal ?? null,
    phase: out.phase ?? null,
    has_judge: out.has_judge,
    is_recurring: out.is_recurring,
    primary_output: out.primary_output ?? null,
    artifacts_produced: out.artifacts_produced.map((a) => ({
      path: a.path,
      description: a.description,
      required: a.required,
    })),
    artifacts_consumed: out.artifacts_consumed.map((a) => ({
      path: a.path,
      description: a.description,
      required: a.required,
    })),
    body_markdown: out.body_markdown,
  };
}

function mapAgentDetail(out: AgentDetailOut): AgentDetail {
  return {
    name: out.name,
    description: out.description,
    model: out.model,
    body_markdown: out.body_markdown,
  };
}

export async function getSystemOverview(): Promise<SystemSnapshot> {
  const { data, error } = await apiClient.GET("/api/system/overview");
  if (error) throw new Error((error as { title?: string }).title || "Failed to get system overview");
  return mapOverview(data as SystemOverviewOut);
}

export async function getSkillDetail(name: string): Promise<SkillDetail> {
  const { data, error } = await apiClient.GET("/api/system/skills/{name}", {
    params: { path: { name } },
  });
  if (error) throw new Error((error as { title?: string }).title || "Failed to get skill detail");
  return mapSkillDetail(data as SkillDetailOut);
}

export async function getAgentDetail(name: string): Promise<AgentDetail> {
  const { data, error } = await apiClient.GET("/api/system/agents/{name}", {
    params: { path: { name } },
  });
  if (error) throw new Error((error as { title?: string }).title || "Failed to get agent detail");
  return mapAgentDetail(data as AgentDetailOut);
}
