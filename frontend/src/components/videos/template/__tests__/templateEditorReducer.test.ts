import { describe, expect, it } from "vitest";
import type { TemplateMeta } from "@/api/videos";
import {
  templateEditorReducer,
  isDirty,
  buildPatch,
} from "../templateEditorReducer";
import type { TemplateEditorState } from "../templateEditorReducer";

// ───────── fixtures ─────────

const baseMeta: TemplateMeta = {
  id: "tpl-001",
  name: "Base Name",
  description: "Base description",
  expected_duration_seconds: 60,
  intended_audience: "CHW supervisors",
  when_to_use: "Onboarding",
};

function freshState(): TemplateEditorState {
  return templateEditorReducer(
    // initial state doesn't matter — init replaces everything
    {} as TemplateEditorState,
    {
      type: "init",
      payload: {
        meta: { ...baseMeta },
        promptMd: "# Prompt",
        skeletonYaml: "skeleton: true",
        exampleYaml: "example: true",
      },
    },
  );
}

// ───────── init ─────────

describe("templateEditorReducer — init", () => {
  it("sets all fields and baseline from the payload", () => {
    const s = freshState();
    expect(s.meta).toEqual(baseMeta);
    expect(s.promptMd).toBe("# Prompt");
    expect(s.skeletonYaml).toBe("skeleton: true");
    expect(s.exampleYaml).toBe("example: true");
    expect(s.baseline.meta).toEqual(baseMeta);
    expect(s.baseline.promptMd).toBe("# Prompt");
  });
});

// ───────── isDirty / buildPatch — no edits ─────────

describe("isDirty + buildPatch — no edits", () => {
  it("isDirty is false after init with no mutations", () => {
    expect(isDirty(freshState())).toBe(false);
  });

  it("buildPatch returns an empty object after init with no mutations", () => {
    expect(buildPatch(freshState())).toEqual({});
  });
});

// ───────── set-meta-field ─────────

describe("set-meta-field", () => {
  it("description change: isDirty true, buildPatch contains only meta.description", () => {
    const s = templateEditorReducer(freshState(), {
      type: "set-meta-field",
      field: "description",
      value: "Updated desc",
    });
    expect(isDirty(s)).toBe(true);
    expect(buildPatch(s)).toEqual({ meta: { description: "Updated desc" } });
  });

  it("name change: buildPatch contains only meta.name", () => {
    const s = templateEditorReducer(freshState(), {
      type: "set-meta-field",
      field: "name",
      value: "New Name",
    });
    expect(buildPatch(s)).toEqual({ meta: { name: "New Name" } });
  });

  it("numeric field change (expected_duration_seconds): patch carries number value", () => {
    const s = templateEditorReducer(freshState(), {
      type: "set-meta-field",
      field: "expected_duration_seconds",
      value: 90,
    });
    expect(buildPatch(s)).toEqual({ meta: { expected_duration_seconds: 90 } });
  });

  it("editing a meta field back to its baseline value: not dirty for that field", () => {
    let s = templateEditorReducer(freshState(), {
      type: "set-meta-field",
      field: "description",
      value: "Temporary",
    });
    expect(isDirty(s)).toBe(true);

    s = templateEditorReducer(s, {
      type: "set-meta-field",
      field: "description",
      value: baseMeta.description, // back to original
    });
    expect(isDirty(s)).toBe(false);
    expect(buildPatch(s)).toEqual({});
  });
});

// ───────── set-prompt ─────────

describe("set-prompt", () => {
  it("buildPatch returns { prompt_md } and nothing else", () => {
    const s = templateEditorReducer(freshState(), {
      type: "set-prompt",
      value: "# New Prompt\n\nBe precise.",
    });
    expect(isDirty(s)).toBe(true);
    expect(buildPatch(s)).toEqual({ prompt_md: "# New Prompt\n\nBe precise." });
  });

  it("editing prompt back to baseline clears dirty", () => {
    let s = templateEditorReducer(freshState(), {
      type: "set-prompt",
      value: "changed",
    });
    s = templateEditorReducer(s, { type: "set-prompt", value: "# Prompt" });
    expect(isDirty(s)).toBe(false);
    expect(buildPatch(s)).toEqual({});
  });
});

// ───────── set-skeleton ─────────

describe("set-skeleton", () => {
  it("buildPatch returns { skeleton_yaml } and nothing else", () => {
    const s = templateEditorReducer(freshState(), {
      type: "set-skeleton",
      value: "skeleton: updated",
    });
    expect(buildPatch(s)).toEqual({ skeleton_yaml: "skeleton: updated" });
  });
});

// ───────── set-example ─────────

describe("set-example", () => {
  it("buildPatch returns { example_yaml } and nothing else", () => {
    const s = templateEditorReducer(freshState(), {
      type: "set-example",
      value: "example: updated",
    });
    expect(buildPatch(s)).toEqual({ example_yaml: "example: updated" });
  });
});

// ───────── combined mutations ─────────

describe("combined mutations", () => {
  it("set-skeleton + set-example + set-meta-field name → patch has those three, no prompt_md", () => {
    let s = freshState();
    s = templateEditorReducer(s, { type: "set-skeleton", value: "skeleton: v2" });
    s = templateEditorReducer(s, { type: "set-example", value: "example: v2" });
    s = templateEditorReducer(s, { type: "set-meta-field", field: "name", value: "New Name" });

    const patch = buildPatch(s);
    expect(patch).toEqual({
      meta: { name: "New Name" },
      skeleton_yaml: "skeleton: v2",
      example_yaml: "example: v2",
    });
    // prompt_md must be absent
    expect("prompt_md" in patch).toBe(false);
  });

  it("all four fields changed → patch includes all four", () => {
    let s = freshState();
    s = templateEditorReducer(s, { type: "set-prompt", value: "new prompt" });
    s = templateEditorReducer(s, { type: "set-skeleton", value: "new skeleton" });
    s = templateEditorReducer(s, { type: "set-example", value: "new example" });
    s = templateEditorReducer(s, { type: "set-meta-field", field: "description", value: "new desc" });

    const patch = buildPatch(s);
    expect(patch.prompt_md).toBe("new prompt");
    expect(patch.skeleton_yaml).toBe("new skeleton");
    expect(patch.example_yaml).toBe("new example");
    expect(patch.meta).toEqual({ description: "new desc" });
  });

  it("partial meta revert: only still-changed meta keys in patch.meta", () => {
    let s = freshState();
    s = templateEditorReducer(s, { type: "set-meta-field", field: "name", value: "Name A" });
    s = templateEditorReducer(s, { type: "set-meta-field", field: "description", value: "Desc B" });
    // Revert name to original
    s = templateEditorReducer(s, { type: "set-meta-field", field: "name", value: baseMeta.name });

    const patch = buildPatch(s);
    expect(patch).toEqual({ meta: { description: "Desc B" } });
    expect((patch.meta as Record<string, unknown>).name).toBeUndefined();
  });

  it("all meta fields reverted → meta key omitted from patch entirely", () => {
    let s = freshState();
    s = templateEditorReducer(s, { type: "set-meta-field", field: "name", value: "Tmp" });
    s = templateEditorReducer(s, { type: "set-meta-field", field: "name", value: baseMeta.name });

    const patch = buildPatch(s);
    expect("meta" in patch).toBe(false);
  });
});
