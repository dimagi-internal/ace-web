import { useBeatEditor } from "../BeatEditorContext";

// The motion-graphic "card" beat (body_ai_build): headline + chips + subhead.
// Click to edit in the drawer. Only rendered in the template editor
// (fullEdit) — the workbench has no backend op for ai_build content.
export function AiBuildWidget({ beatId }: { beatId: string }) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  const card = effectiveSpec.ai_build;
  if (!card) return null;
  return (
    <div
      data-testid="ai-build-widget"
      className="group cursor-pointer rounded border bg-muted/20 p-3 hover:border-primary"
      onClick={() => dispatch({ type: "OPEN_DRAWER", target: { kind: "ai-build", beatId } })}
    >
      <header className="mb-1 flex items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Card
        </span>
        <span aria-hidden className="ml-auto text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
          ✏ Edit
        </span>
      </header>
      <div className="text-base font-semibold">{card.headline || "(no headline — click to add)"}</div>
      {card.components.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {card.components.map((c, i) => (
            <span key={i} className="rounded-full border bg-background px-2 py-0.5 text-xs">
              {c}
            </span>
          ))}
        </div>
      )}
      {card.subhead && <div className="mt-2 text-sm text-muted-foreground">{card.subhead}</div>}
    </div>
  );
}
