import { useState } from "react";
import { ChevronsDownUp, ChevronsUpDown } from "lucide-react";
import { useBeatEditor } from "./BeatEditorContext";
import { BeatCard } from "./BeatCard";
import { ClipSlotWidget } from "./widgets/ClipSlotWidget";
import { NarrationWidget } from "./widgets/NarrationWidget";
import { StatsWidget } from "./widgets/StatsWidget";
import { BrandTemplateWidget } from "./widgets/BrandTemplateWidget";
import type { ProgramSpec } from "./types";

export function BeatList() {
  const { effectiveSpec } = useBeatEditor();
  const beats = effectiveSpec.beats ?? [];
  // Set of beat-ids currently collapsed. Default = empty (all
  // expanded). The expand-all / collapse-all toggle flips between
  // empty and "all beat ids" so users can use the collapsed headers
  // as a scannable outline of the video.
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
  const allCollapsed = beats.length > 0 && beats.every((b) => collapsedIds.has(b.id));

  const toggleOne = (id: string) =>
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleAll = () => {
    if (allCollapsed) setCollapsedIds(new Set());
    else setCollapsedIds(new Set(beats.map((b) => b.id)));
  };

  let cursor = 0;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-end">
        <button
          type="button"
          onClick={toggleAll}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          title={allCollapsed ? "Expand every beat" : "Collapse every beat (outline view)"}
        >
          {allCollapsed ? (
            <>
              <ChevronsUpDown className="h-3.5 w-3.5" />
              Expand all
            </>
          ) : (
            <>
              <ChevronsDownUp className="h-3.5 w-3.5" />
              Collapse all
            </>
          )}
        </button>
      </div>
      {beats.map((b) => {
        const startSec = cursor;
        const endSec = cursor + b.seconds;
        cursor += b.seconds;
        return (
          <BeatCard
            key={b.id}
            beatId={b.id}
            kind={b.kind}
            startSec={startSec}
            endSec={endSec}
            collapsed={collapsedIds.has(b.id)}
            onToggleCollapsed={() => toggleOne(b.id)}
          >
            <NarrationWidget beatId={b.id} />
            {renderKindBody(b.id, b.kind, effectiveSpec)}
          </BeatCard>
        );
      })}
    </div>
  );
}

function renderKindBody(beatId: string, kind: string, spec: ProgramSpec) {
  if (kind === "body_scene") {
    return (spec.scene?.clips ?? []).map((_, i) => (
      <ClipSlotWidget key={i} beatId={beatId} clipKind="scene-clip" index={i} />
    ));
  }
  if (kind === "body_product_beats") {
    return (spec.product?.beats ?? []).map((_, i) => (
      <ClipSlotWidget key={i} beatId={beatId} clipKind="product-beat" index={i} />
    ));
  }
  if (kind === "body_problem_stat") {
    return <StatsWidget beatId={beatId} path="problem" />;
  }
  if (kind === "body_impact_stats") {
    return (spec.impact ?? []).map((_, i) => (
      <StatsWidget key={i} beatId={beatId} path={`impact[${i}]`} />
    ));
  }
  return <BrandTemplateWidget beatId={beatId} kind={kind} />;
}
