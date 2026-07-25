import type { Decision } from "@/api/types.ws";

import type { EditOp } from "./decisionsReducer";

/**
 * Client-only escape hatch: serialize whatever is locally true — the
 * staged edit buffer joined with each decision's context — into a
 * downloadable document. Exists for the day the server side is broken
 * (WS down, save endpoint erroring): a reviewer's work must always have
 * a way out of the tab.
 *
 * The row shape mirrors `inputs/decision-overrides.yaml` (see
 * apps/opps/decision_overrides.py) so the export can be used to
 * reconstruct the Drive file by hand. Emitted as JSON, not YAML — no
 * client-side YAML emitter means no escaping bugs in free-text
 * reasoning, and JSON→YAML is trivial for whoever picks the file up.
 */

export interface LocalOverrideRow {
  id: string;
  phase: string;
  question: string;
  ai_default: string;
  override: string;
  override_reasoning?: string;
  decided_by: string;
  decided_at: string;
  source_run_id: string;
}

export interface LocalOverridesExport {
  kind: "decision-overrides-local-export";
  schema_version: 1;
  opp: string;
  exported_at: string;
  overrides: LocalOverrideRow[];
}

export function buildDecisionOverridesExport({
  oppSlug,
  runId,
  edits,
  decisions,
}: {
  oppSlug: string;
  runId: string;
  edits: readonly EditOp[];
  decisions: readonly Decision[];
}): LocalOverridesExport {
  const byId = new Map(decisions.map((d) => [d.id, d]));
  const overrides: LocalOverrideRow[] = edits.map((edit) => {
    // A buffered edit whose row_id no longer resolves still exports —
    // "locally true" beats "joinable"; the context fields just stay empty.
    const source = byId.get(edit.row_id);
    const row: LocalOverrideRow = {
      id: edit.row_id,
      phase: source?.phase ?? "",
      question: source?.question ?? "",
      ai_default: source?.ai_default ?? "",
      override: edit.new_answer,
      decided_by: edit.editor_email ?? "",
      decided_at: new Date().toISOString(),
      source_run_id: runId,
    };
    const reasoning = (edit.override_reasoning ?? "").trim();
    if (reasoning) row.override_reasoning = reasoning;
    return row;
  });
  return {
    kind: "decision-overrides-local-export",
    schema_version: 1,
    opp: oppSlug,
    exported_at: new Date().toISOString(),
    overrides,
  };
}

/** Trigger a browser download of the export document. Pure client-side. */
export function downloadDecisionOverrides(doc: LocalOverridesExport): void {
  const stamp = doc.exported_at.replace(/[:.]/g, "-");
  const filename = `decision-overrides-${doc.opp}-${stamp}.json`;
  const blob = new Blob([JSON.stringify(doc, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
