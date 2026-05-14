import { apiV2 } from "./client.v2";
import type { StructureTree } from "./types.ws";

/**
 * structure.ts — session structure tree API client (v2).
 *
 * v2 endpoint: GET /api/w/{workspace_slug}/sessions/{slug}/structure
 * The response body is not captured in the generated schema (content?: never),
 * so we cast the raw JSON to `StructureTree`.
 */
export async function getSessionStructure(
  slug: string,
  workspaceSlug: string,
): Promise<StructureTree> {
  const { response } = await apiV2.GET(
    "/api/w/{workspace_slug}/sessions/{slug}/structure",
    { params: { path: { workspace_slug: workspaceSlug, slug } } },
  );
  if (!response.ok) throw new Error(`Failed to get session structure: ${response.status}`);
  return (await response.json()) as StructureTree;
}
