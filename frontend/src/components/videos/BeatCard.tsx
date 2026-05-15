import { useBeatEditor } from "./BeatEditorContext";
import { opCoalesceKey, type PendingChange } from "./types";
import type { ReactNode } from "react";

const SECTION_LABELS: Record<string, { name: string; subtitle: string }> = {
  hook: { name: "Opening tagline", subtitle: "Headline that frames the video." },
  cycle: { name: "How Connect works", subtitle: "Learn → Deliver → Verify → Pay cycle." },
  handoff: { name: "Program handoff", subtitle: "Names this specific program." },
  scene: { name: "Field footage", subtitle: "Real footage from the program location." },
  problem: { name: "Headline stat", subtitle: "One big number that frames the problem." },
  product: { name: "Connect app walkthrough", subtitle: "Short phone-frame clips." },
  impact: { name: "Results numbers", subtitle: "Two big numbers — what the program delivered." },
  cta: { name: "End card", subtitle: "Logo + tagline + 'become a partner'." },
};

interface Props {
  beatId: string;
  kind: string;
  startSec: number;
  endSec: number;
  children: ReactNode;
}

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function beatIsDirty(beatId: string, kind: string, buffer: PendingChange[]): boolean {
  return buffer.some((op) => {
    const k = opCoalesceKey(op);
    if (k === `set-narration:${beatId}`) return true;
    if (k === "set-stat:problem" && kind === "body_problem_stat") return true;
    if (k.startsWith("set-stat:impact") && kind === "body_impact_stats") return true;
    if (k.includes("scene-clip") && kind === "body_scene") return true;
    if (k.includes("product-beat") && kind === "body_product_beats") return true;
    return false;
  });
}

export function BeatCard({ beatId, kind, startSec, endSec, children }: Props) {
  const { state } = useBeatEditor();
  const label = SECTION_LABELS[beatId] ?? { name: beatId, subtitle: "" };
  const dirty = beatIsDirty(beatId, kind, state.buffer);
  return (
    <section
      data-beat-id={beatId}
      className="rounded-md border bg-card p-4"
      style={{
        outline: dirty ? "2px solid #FBBF24" : undefined,
        outlineOffset: -2,
      }}
    >
      <header className="mb-3 flex items-baseline gap-3">
        <h3 className="text-base font-semibold">{label.name}</h3>
        <span className="font-mono text-xs text-muted-foreground">
          {fmt(startSec)} → {fmt(endSec)} · {(endSec - startSec).toFixed(1)}s
        </span>
        {dirty && (
          <span className="ml-auto rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
            edited
          </span>
        )}
      </header>
      {label.subtitle && (
        <p className="mb-3 text-sm text-muted-foreground">{label.subtitle}</p>
      )}
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  );
}
