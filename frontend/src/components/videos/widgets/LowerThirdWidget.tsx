import { useBeatEditor } from "../BeatEditorContext";

// The scene beat's lower-third caption (spec.scene.lower_third) — the text
// overlaid on the field footage. Click to edit in the drawer.
export function LowerThirdWidget({ beatId }: { beatId: string }) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  if (!effectiveSpec.scene) return null;
  const text = effectiveSpec.scene.lower_third ?? "";
  return (
    <div
      data-testid="lower-third-widget"
      className="group cursor-pointer rounded border bg-muted/20 p-3 hover:border-primary"
      onClick={() => dispatch({ type: "OPEN_DRAWER", target: { kind: "lower-third", beatId } })}
    >
      <header className="mb-1 flex items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Lower third
        </span>
        <span aria-hidden className="ml-auto text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
          ✏ Edit
        </span>
      </header>
      <p className={text.trim() ? "text-sm" : "text-sm italic text-muted-foreground"}>
        {text.trim() || "(no lower third — click to add)"}
      </p>
    </div>
  );
}
