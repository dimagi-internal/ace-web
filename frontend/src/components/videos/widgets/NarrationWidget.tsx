import { useBeatEditor } from "../BeatEditorContext";

export function NarrationWidget({ beatId }: { beatId: string }) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  const text = effectiveSpec.narration?.by_beat?.[beatId] ?? "";
  const wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
  const estSec = Math.round((text.length / 15) * 10) / 10;

  return (
    <div
      data-testid="narration-widget"
      data-beat={beatId}
      className="group cursor-pointer rounded border bg-muted/20 p-3 hover:border-primary"
      onClick={() => dispatch({ type: "OPEN_DRAWER", target: { kind: "narration", beatId } })}
    >
      <header className="mb-1 flex items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Voiceover
        </span>
        <span aria-hidden className="ml-auto text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
          ✏ Edit
        </span>
      </header>
      <p className={text.trim() ? "text-sm" : "text-sm italic text-muted-foreground"}>
        {text.trim() || "(no narration — click to add)"}
      </p>
      <div className="mt-1 text-xs text-muted-foreground">
        {wordCount} word{wordCount === 1 ? "" : "s"} · ~{estSec}s read
      </div>
    </div>
  );
}
