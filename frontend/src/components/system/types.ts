import type { PhaseInfo } from "../../api/types";
export type { PhaseInfo } from "../../api/types";

export interface ArtifactRef {
  path: string;
  description: string;
  required: boolean;
}

export interface ArtifactEntry {
  path: string;
  produced_by: string;
  consumed_by: string[];
  phase: string;
  required: boolean;
  description: string;
}

export interface SkillSummary {
  name: string;
  display_name: string;
  description: string;
  ordinal: number | null;
  phase: string | null;
  has_judge: boolean;
  is_recurring: boolean;
  primary_output: string | null;
  artifacts_produced: ArtifactRef[];
  artifacts_consumed: ArtifactRef[];
}

export interface SkillDetail extends SkillSummary {
  body_markdown: string;
}

export interface AgentSummary {
  name: string;
  description: string;
  model: string;
}

export interface AgentDetail extends AgentSummary {
  body_markdown: string;
}

export interface SystemSnapshot {
  plugin_version: string | null;
  remote_version: string | null;
  update_available: boolean | null;
  skills: SkillSummary[];
  agents: AgentSummary[];
  artifacts: ArtifactEntry[];
  phases: PhaseInfo[];
  warning: string | null;
}
