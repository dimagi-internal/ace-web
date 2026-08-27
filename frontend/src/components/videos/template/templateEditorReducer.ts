import type { TemplateMeta, TemplateMetaPatch, TemplatePatchIn } from "@/api/videos";

// ───────── state ─────────

export interface TemplateEditorBaseline {
  meta: TemplateMeta;
  promptMd: string;
  exampleYaml: string;
}

export interface TemplateEditorState {
  meta: TemplateMeta;
  promptMd: string;
  exampleYaml: string;
  /** Pristine snapshot loaded via "init" — used to compute the patch. */
  baseline: TemplateEditorBaseline;
}

// ───────── actions ─────────

export type TemplateEditorAction =
  | { type: "init"; payload: TemplateEditorBaseline }
  | { type: "set-meta-field"; field: keyof Omit<TemplateMeta, "id">; value: string | number }
  | { type: "set-prompt"; value: string }
  | { type: "set-example"; value: string }
  // Refresh the read-only example YAML after the BeatEditor persisted it —
  // updates the displayed value AND its baseline so it isn't flagged dirty.
  | { type: "sync-example"; value: string };

// ───────── reducer ─────────

export function templateEditorReducer(
  state: TemplateEditorState,
  action: TemplateEditorAction,
): TemplateEditorState {
  switch (action.type) {
    case "init": {
      const { meta, promptMd, exampleYaml } = action.payload;
      return {
        meta: { ...meta },
        promptMd,
        exampleYaml,
        baseline: { meta: { ...meta }, promptMd, exampleYaml },
      };
    }
    case "set-meta-field":
      return {
        ...state,
        meta: { ...state.meta, [action.field]: action.value },
      };
    case "set-prompt":
      return { ...state, promptMd: action.value };
    case "set-example":
      return { ...state, exampleYaml: action.value };
    case "sync-example":
      return {
        ...state,
        exampleYaml: action.value,
        baseline: { ...state.baseline, exampleYaml: action.value },
      };
  }
}

// ───────── helpers ─────────

/** True when any field in `state` differs from the baseline snapshot. */
export function isDirty(state: TemplateEditorState): boolean {
  const { meta, promptMd, exampleYaml, baseline: b } = state;
  if (promptMd !== b.promptMd) return true;
  if (exampleYaml !== b.exampleYaml) return true;
  // Check each editable meta field individually (never compare `id`).
  const metaKeys: Array<keyof Omit<TemplateMeta, "id">> = [
    "name",
    "description",
    "intent",
    "intended_audience",
    "when_to_use",
  ];
  for (const k of metaKeys) {
    if (meta[k] !== b.meta[k]) return true;
  }
  return false;
}

/**
 * Build a minimal `TemplatePatchIn` containing ONLY the fields that differ
 * from the baseline.  Fields whose current value matches the baseline are
 * omitted entirely.
 */
export function buildPatch(state: TemplateEditorState): TemplatePatchIn {
  const { meta, promptMd, exampleYaml, baseline: b } = state;
  const patch: TemplatePatchIn = {};

  // ── meta sub-object ────────────────────────────────────────────────────
  const metaKeys: Array<keyof Omit<TemplateMeta, "id">> = [
    "name",
    "description",
    "intent",
    "intended_audience",
    "when_to_use",
  ];
  const metaPatch: TemplateMetaPatch = {};
  let anyMetaChanged = false;
  for (const k of metaKeys) {
    if (meta[k] !== b.meta[k]) {
      // Cast: TemplateMetaPatch keys are all optional and accept string|number.
      (metaPatch as Record<string, string | number>)[k] = meta[k];
      anyMetaChanged = true;
    }
  }
  if (anyMetaChanged) patch.meta = metaPatch;

  // ── top-level text fields ──────────────────────────────────────────────
  if (promptMd !== b.promptMd) patch.prompt_md = promptMd;
  if (exampleYaml !== b.exampleYaml) patch.example_yaml = exampleYaml;

  return patch;
}
