import { useBeatEditor } from "./BeatEditorContext";
import { opCoalesceKey } from "./types";

// Plain-language labels and kind→color map mirror build-clip-explorer.ts:113.
// Keep in sync if the framework adds new BeatKinds.
const SECTION_LABELS: Record<string, string> = {
  hook: "Opening tagline", cycle: "How Connect works", handoff: "Program handoff",
  scene: "Field footage", problem: "Headline stat",
  product: "Connect app walkthrough", impact: "Results numbers", cta: "End card",
};
const KIND_COLORS: Record<string, string> = {
  intro_hook: "#3843D0", intro_cycle: "#3843D0", intro_handoff: "#3843D0",
  body_scene: "#22A06B", body_problem_stat: "#E45A3A",
  body_product_beats: "#FEAF31", body_impact_stats: "#22A06B",
  outro_cta: "#3843D0",
};

export function TimelineStrip() {
  const { state, effectiveSpec } = useBeatEditor();
  const beats = effectiveSpec.beats ?? [];
  const total = beats.reduce((s, b) => s + b.seconds, 0) || 1;

  // A beat is "dirty" if buffer has any op targeting it.
  const dirtyBeats = new Set(
    state.buffer
      .map((op) => {
        const k = opCoalesceKey(op);
        if (k.startsWith("set-narration:")) return k.split(":")[1];
        if (k.startsWith("set-stat:problem")) return "problem";
        if (k.startsWith("set-stat:impact")) return "impact";
        // clip ops live in scene/product
        if (k.includes("scene-clip")) return "scene";
        if (k.includes("product-beat")) return "product";
        return null;
      })
      .filter(Boolean) as string[],
  );

  let cursor = 0;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        {beats.map((b) => (
          <span key={b.id} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: KIND_COLORS[b.kind] ?? "#3843D0" }}
            />
            {SECTION_LABELS[b.id] ?? b.id}
          </span>
        ))}
      </div>
      <div className="relative h-4 w-full overflow-hidden rounded bg-muted">
        {beats.map((b) => {
          const left = (cursor / total) * 100;
          const width = (b.seconds / total) * 100;
          cursor += b.seconds;
          return (
            <button
              type="button"
              key={b.id}
              className="absolute top-0 bottom-0"
              style={{
                left: `${left}%`, width: `${width}%`,
                background: KIND_COLORS[b.kind] ?? "#3843D0",
                opacity: 0.92,
                outline: dirtyBeats.has(b.id) ? "2px solid #FBBF24" : undefined,
                outlineOffset: -2,
              }}
              title={`${SECTION_LABELS[b.id] ?? b.id} · ${b.seconds.toFixed(1)}s`}
              onClick={() => {
                document
                  .querySelector(`[data-beat-id="${b.id}"]`)
                  ?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
            />
          );
        })}
      </div>
    </div>
  );
}
