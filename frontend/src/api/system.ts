import { request } from "./client";
import type { AgentDetail, SkillDetail, SystemSnapshot } from "../components/system/types";

export function getSystemOverview(): Promise<SystemSnapshot> {
  return request<SystemSnapshot>("/system/overview");
}

export function getSkillDetail(name: string): Promise<SkillDetail> {
  return request<SkillDetail>(`/system/skills/${encodeURIComponent(name)}`);
}

export function getAgentDetail(name: string): Promise<AgentDetail> {
  return request<AgentDetail>(`/system/agents/${encodeURIComponent(name)}`);
}
