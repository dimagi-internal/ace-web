import { useBeatEditor } from "../BeatEditorContext";

/**
 * Minimal editor widget for a walkthrough-arc `body_walkthrough` beat
 * (connect-walkthrough template).
 *
 * A walkthrough beat plays a RANGE of one master clip full-bleed with a
 * lower-third; its voiceover rides on the shared NarrationWidget (which
 * BeatList already renders for every beat). This widget just surfaces
 * the clip slot (alias + range into the master clip) and the
 * lower-third so the beat doesn't fall through to the GlobalTemplate
 * widget and read as "no content". Read-only for now — clip swap/trim
 * and lower-third edit are deferred; this is enough that the walkthrough
 * arc renders coherently in the editor.
 */
function aliasFromRef(ref: string): string {
  return ref.startsWith("@") ? ref.slice(1) : ref;
}

export function WalkthroughWidget({ beatId }: { beatId: string }) {
  const { effectiveSpec } = useBeatEditor();
  const wt = effectiveSpec.walkthrough?.[beatId];
  if (!wt) {
    return (
      <div className="rounded border border-dashed bg-muted/20 p-3 text-sm italic text-muted-foreground">
        No walkthrough clip configured for this section.
      </div>
    );
  }
  const start = wt.start_seconds ?? 0;
  const dur = wt.duration_seconds;
  const range =
    dur !== undefined
      ? `${start.toFixed(1)}s → ${(start + dur).toFixed(1)}s of master clip`
      : `from ${start.toFixed(1)}s of master clip`;
  return (
    <div data-testid="walkthrough-widget" data-beat={beatId} className="flex flex-col gap-2">
      <div className="rounded border bg-muted/40 p-3">
        <header className="mb-1 flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Walkthrough clip
          </span>
          <code className="rounded bg-muted px-1.5 py-0.5 text-xs">@{aliasFromRef(wt.asset)}</code>
        </header>
        <div className="font-mono text-xs text-muted-foreground">{range}</div>
      </div>
      <div className="rounded border bg-muted/20 p-3">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Lower-third
        </span>
        <p className="mt-1 text-sm">{wt.lower_third}</p>
      </div>
    </div>
  );
}
