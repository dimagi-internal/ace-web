import { useEffect, useReducer, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ChevronLeft } from "lucide-react";

import {
  getTemplateExampleSpec,
  getVideoTemplate,
  listVideoTemplates,
  patchTemplate,
  type TemplateMeta,
} from "@/api/videos";
import type { ProgramSpec } from "@/components/videos/types";
import { WorkbenchLayout, usePaneCollapsed } from "@/components/workbench";
import { Skeleton } from "@canopy/workbench/ui";
import { BeatEditor } from "@/components/videos/BeatEditor";
import { TemplateMetaPanel } from "@/components/videos/template/TemplateMetaPanel";
import { TemplateExamplePanel } from "@/components/videos/template/TemplateExamplePanel";
import { TemplateNavRail } from "@/components/videos/template/TemplateNavRail";
import {
  buildPatch,
  isDirty,
  templateEditorReducer,
  type TemplateEditorState,
} from "@/components/videos/template/templateEditorReducer";

// ──────────────────────────────────────────────────────────────────────────────
// Save-state machine — same shape as BeatEditorTopBar's saveState
// ──────────────────────────────────────────────────────────────────────────────

type SaveStatus =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved"; at: number }
  | { status: "error"; message: string };

// Initial reducer state — kept outside the component to avoid re-creation.
const EMPTY_META: TemplateMeta = {
  id: "",
  name: "",
  description: "",
  intent: "",
  intended_audience: "",
  when_to_use: "",
};

function initialState(): TemplateEditorState {
  return {
    meta: EMPTY_META,
    promptMd: "",
    exampleYaml: "",
    baseline: {
      meta: EMPTY_META,
      promptMd: "",
      exampleYaml: "",
    },
  };
}

// ──────────────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────────────

export default function TemplateEditorPage() {
  const { workspaceSlug, templateId } = useParams<{
    workspaceSlug: string;
    templateId: string;
  }>();

  const [state, dispatch] = useReducer(templateEditorReducer, undefined, initialState);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveStatus>({ status: "idle" });

  // Parsed example spec for the BeatEditor. Loaded alongside the bundle.
  const [exampleSpec, setExampleSpec] = useState<ProgramSpec | null>(null);
  // Toggle: show the BeatEditor (primary) vs raw YAML textarea (advanced).
  const [showRawYaml, setShowRawYaml] = useState(false);

  // Left-rail template list
  const [templates, setTemplates] = useState<TemplateMeta[] | null>(null);
  const { collapsed: railCollapsed, toggle: toggleRailCollapsed } =
    usePaneCollapsed("ace.templateEditor.railCollapsed");

  // Load the template list for the left rail.
  useEffect(() => {
    if (!workspaceSlug) return;
    let cancelled = false;
    listVideoTemplates(workspaceSlug)
      .then((data) => {
        if (!cancelled) setTemplates(data);
      })
      .catch(() => {
        // Rail is secondary — swallow; the main panel has its own error state.
        if (!cancelled) setTemplates([]);
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceSlug]);

  // Load the template bundle + example (YAML + parsed spec) in one effect.
  useEffect(() => {
    if (!workspaceSlug || !templateId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      // The bundle now carries the example YAML (the canonical example spec).
      getVideoTemplate(workspaceSlug, templateId),
      // Parsed spec for the BeatEditor — a separate endpoint.
      // Falls back gracefully if it 404s (e.g. no example.spec.yaml yet).
      getTemplateExampleSpec(workspaceSlug, templateId).catch(() => null),
    ])
      .then(([bundle, exampleSpecOut]) => {
        if (cancelled) return;
        dispatch({
          type: "init",
          payload: {
            meta: bundle.meta,
            promptMd: bundle.prompt_md,
            exampleYaml: bundle.example_yaml ?? "",
          },
        });
        setExampleSpec(exampleSpecOut?.spec ?? null);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [workspaceSlug, templateId]);

  const dirty = isDirty(state);

  async function handleSave() {
    if (!workspaceSlug || !templateId || !dirty || saveState.status === "saving") return;
    setSaveState({ status: "saving" });
    try {
      const patch = buildPatch(state);
      const bundle = await patchTemplate(workspaceSlug, templateId, patch);
      dispatch({
        type: "init",
        payload: {
          meta: bundle.meta,
          promptMd: bundle.prompt_md,
          exampleYaml: bundle.example_yaml ?? "",
        },
      });
      setSaveState({ status: "saved", at: Date.now() });
    } catch (e: unknown) {
      setSaveState({ status: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }

  // Called by the BeatEditor's onSave when the user saves changes to the example spec.
  async function handleExampleSpecSave(effectiveSpec: ProgramSpec): Promise<void> {
    if (!workspaceSlug || !templateId) return;
    // patchTemplate returns the refreshed bundle whose example_yaml is the
    // server's re-serialized spec — use it to update the read-only mirror.
    const bundle = await patchTemplate(workspaceSlug, templateId, { example_spec: effectiveSpec });
    // Optimistically update the local spec so the BeatEditor reflects the saved state.
    setExampleSpec(effectiveSpec);
    // Refresh the read-only raw-YAML reference so it mirrors what was persisted.
    // The visual editor is the source of truth; a stale mirror is non-fatal.
    if (bundle.example_yaml != null) {
      dispatch({ type: "sync-example", value: bundle.example_yaml });
    }
  }

  // ── rail content ──────────────────────────────────────────────────────────

  const railContent = (
    <TemplateNavRail
      workspaceSlug={workspaceSlug ?? ""}
      templates={templates}
      currentTemplateId={templateId ?? ""}
      hasExample={exampleSpec != null}
      beats={exampleSpec?.beats ?? []}
    />
  );

  // ── save button label ─────────────────────────────────────────────────────

  let saveBtnLabel: string;
  if (saveState.status === "saving") {
    saveBtnLabel = "Saving…";
  } else if (saveState.status === "saved") {
    saveBtnLabel = `Saved at ${new Date(saveState.at).toLocaleTimeString()}`;
  } else {
    saveBtnLabel = "Save";
  }

  // ── center content ────────────────────────────────────────────────────────

  const centerContent = (
    <div className="mx-auto max-w-3xl px-6 py-8">
      {/* Page header */}
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <Link
          to={`/w/${workspaceSlug}/videos/templates`}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          All templates
        </Link>
        <h1 className="text-xl font-semibold">
          {loading ? (
            <Skeleton className="h-6 w-48" />
          ) : (
            state.meta.name || templateId
          )}
        </h1>
        <div className="ml-auto flex items-center gap-2">
          {saveState.status === "error" && (
            <span className="flex items-center gap-1 text-xs text-destructive">
              <AlertTriangle className="h-3.5 w-3.5" />
              {saveState.message}
            </span>
          )}
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={!dirty || saveState.status === "saving"}
            className="rounded bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {saveBtnLabel}
          </button>
        </div>
      </header>

      {/* Load error */}
      {error && (
        <div className="mb-6 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 text-destructive" />
          <div>
            <div className="font-medium">Couldn&apos;t load template</div>
            <div className="text-muted-foreground">{error}</div>
          </div>
        </div>
      )}

      {loading && !error ? (
        <div className="flex flex-col gap-6">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : !error ? (
        // Key by templateId so switching templates remounts the panels and
        // their AutoResizeTextareas re-fit the new content on open.
        <div key={templateId} className="flex flex-col gap-10">
          {/* ── Metadata ─────────────────────────────────────────────────── */}
          <section id="tpl-section-metadata" className="scroll-mt-4">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Metadata
            </h2>
            <TemplateMetaPanel meta={state.meta} dispatch={dispatch} />
          </section>

          <hr className="border-border" />

          {/* ── Demo / example ───────────────────────────────────────────── */}
          <section id="tpl-section-demo" className="scroll-mt-4">
            <div className="mb-4 flex items-center gap-3">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Demo / example
              </h2>
              <button
                type="button"
                onClick={() => setShowRawYaml((v) => !v)}
                className="ml-auto rounded border px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted"
              >
                {showRawYaml ? "Visual editor" : "Raw YAML (read-only)"}
              </button>
            </div>
            {showRawYaml ? (
              <TemplateExamplePanel exampleYaml={state.exampleYaml} />
            ) : exampleSpec != null ? (
              <BeatEditor
                workspaceSlug={workspaceSlug ?? ""}
                programSlug={templateId ?? ""}
                runId="example"
                spec={exampleSpec}
                onSave={handleExampleSpecSave}
              />
            ) : (
              /* No parsed spec available yet — fall back to the YAML textarea. */
              <TemplateExamplePanel exampleYaml={state.exampleYaml} />
            )}
          </section>
        </div>
      ) : null}
    </div>
  );

  return (
    <div className="flex h-[calc(100vh-3rem)] flex-col">
      <WorkbenchLayout
        left={{
          title: "Navigator",
          collapsed: railCollapsed,
          onToggle: toggleRailCollapsed,
          expandedWidth: 240,
          minWidth: 180,
          maxWidth: 400,
          resizable: true,
          content: railContent,
        }}
        center={centerContent}
      />
    </div>
  );
}
