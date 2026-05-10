import { apiFetch } from "./client";
import type { StructureTree } from "./types";

export async function getSessionStructure(slug: string): Promise<StructureTree> {
  return apiFetch<StructureTree>(`/api/sessions/${slug}/structure`);
}
