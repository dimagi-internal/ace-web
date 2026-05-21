import { useState } from "react";
import { useBeatEditor } from "../BeatEditorContext";

interface Props {
  beatId: string;
}

/**
 * Per-beat widget for the program handoff card.
 *
 * The handoff beat renders `spec.name` directly ("Here's how that
 * works for <name>"), so it's not a global-template override target
 * like hook/cycle/cta — it edits a different piece of spec entirely.
 *
 * Visually mirrors GlobalTemplateWidget (same dashed border + qa-frame
 * thumbnail) for layout continuity, but labels itself "PROGRAM NAME"
 * and routes clicks to a dedicated Rename-program drawer instead of
 * the global-template drawer.
 */
export function ProgramNameWidget({ beatId }: Props) {
  const { effectiveSpec, dispatch, workspaceSlug, programSlug, runId } = useBeatEditor();
  const [previewMissing, setPreviewMissing] = useState(false);

  const apiPrefix = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const previewSrc = `${apiPrefix}/api/w/${workspaceSlug}/videos/programs/${programSlug}/runs/${runId}/qa-frame/handoff`;
  const showPreview = !previewMissing;

  const programName = (effectiveSpec.name ?? "").trim() || "(unnamed)";

  const openEditor = () =>
    dispatch({
      type: "OPEN_DRAWER",
      target: { kind: "program-name", beatId },
    });

  return (
    <button
      type="button"
      onClick={openEditor}
      className="group flex w-full gap-3 rounded border border-dashed border-sky-700/40 bg-sky-950/5 p-3 text-left transition-colors hover:border-solid focus:outline-none focus:ring-1 focus:ring-primary"
    >
      {showPreview && (
        <div className="flex-shrink-0">
          <img
            src={previewSrc}
            alt=""
            loading="lazy"
            decoding="async"
            onError={() => setPreviewMissing(true)}
            className="aspect-video w-28 rounded border border-border/40 bg-muted object-cover"
          />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-1.5">
          {/* Pencil-edit icon (clickable, matching the other editable
              widgets' affordance vocabulary; never shows lock since
              this isn't a template-override surface). */}
          <svg
            aria-hidden
            className="h-3 w-3 text-sky-600/70"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
          </svg>
          <span className="text-xs font-medium uppercase tracking-wide text-sky-700/80 dark:text-sky-500/80">
            Program name
          </span>
          <span className="ml-auto text-xs text-muted-foreground transition-colors group-hover:text-foreground">
            ✏ Rename
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Handoff card — "Here's how that works for{" "}
          <span className="font-medium text-foreground">{programName}</span>
          ".
        </p>
        <p className="mt-1 text-xs text-muted-foreground/70">
          Renames this program everywhere — handoff card, breadcrumb, run picker, program list.
        </p>
      </div>
    </button>
  );
}
