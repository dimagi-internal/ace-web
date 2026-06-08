import type { TemplateMeta, TemplateMetaPatch, TemplatePatchIn } from "@/api/videos";

// ───────── state ─────────

export interface TemplateEditorBaseline {
  meta: TemplateMeta;
  promptMd: string;
  skeletonYaml: string;
  exampleYaml: string;
}

export interface TemplateEditorState {
  meta: TemplateMeta;
  promptMd: string;
  skeletonYaml: string;
  exampleYaml: string;
  /** Pristine snapshot loaded via "init" — used to compute the patch. */
  baseline: TemplateEditorBaseline;
}

// ───────── actions ─────────

export type TemplateEditorAction =
  | { type: "init"; payload: TemplateEditorBaseline }
  | { type: "set-meta-field"; field: keyof Omit<TemplateMeta, "id">; value: string | number }
  | { type: "set-prompt"; value: string }
  | { type: "set-skeleton"; value: string }
  | { type: "set-example"; value: string };

// ───────── reducer ─────────

export function templateEditorReducer(
  state: TemplateEditorState,
  action: TemplateEditorAction,
): TemplateEditorState {
  switch (action.type) {
    case "init": {
      const { meta, promptMd, skeletonYaml, exampleYaml } = action.payload;
      return {
        meta: { ...meta },
        promptMd,
        skeletonYaml,
        exampleYaml,
        baseline: { meta: { ...meta }, promptMd, skeletonYaml, exampleYaml },
      };
    }
    case "set-meta-field":
      return {
        ...state,
        meta: { ...state.meta, [action.field]: action.value },
      };
    case "set-prompt":
      return { ...state, promptMd: action.value };
    case "set-skeleton":
      return { ...state, skeletonYaml: action.value };
    case "set-example":
      return { ...state, exampleYaml: action.value };
  }
}

// ───────── helpers ─────────

/** True when any field in `state` differs from the baseline snapshot. */
export function isDirty(state: TemplateEditorState): boolean {
  const { meta, promptMd, skeletonYaml, exampleYaml, baseline: b } = state;
  if (promptMd !== b.promptMd) return true;
  if (skeletonYaml !== b.skeletonYaml) return true;
  if (exampleYaml !== b.exampleYaml) return true;
  // Check each editable meta field individually (never compare `id`).
  const metaKeys: Array<keyof Omit<TemplateMeta, "id">> = [
    "name",
    "description",
    "expected_duration_seconds",
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
  const { meta, promptMd, skeletonYaml, exampleYaml, baseline: b } = state;
  const patch: TemplatePatchIn = {};

  // ── meta sub-object ────────────────────────────────────────────────────
  const metaKeys: Array<keyof Omit<TemplateMeta, "id">> = [
    "name",
    "description",
    "expected_duration_seconds",
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
  if (skeletonYaml !== b.skeletonYaml) patch.skeleton_yaml = skeletonYaml;
  if (exampleYaml !== b.exampleYaml) patch.example_yaml = exampleYaml;

  return patch;
}
