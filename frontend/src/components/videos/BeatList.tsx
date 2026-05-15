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
  let cursor = 0;
  return (
    <div className="flex flex-col gap-4">
      {beats.map((b) => {
        const startSec = cursor;
        const endSec = cursor + b.seconds;
        cursor += b.seconds;
        return (
          <BeatCard key={b.id} beatId={b.id} kind={b.kind} startSec={startSec} endSec={endSec}>
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
