import { useState } from "react";
import { ChevronsDownUp, ChevronsUpDown, Plus } from "lucide-react";
import { useBeatEditor } from "./BeatEditorContext";
import { BeatCard } from "./BeatCard";
import { ClipSlotWidget } from "./widgets/ClipSlotWidget";
import { NarrationWidget } from "./widgets/NarrationWidget";
import { WalkthroughWidget } from "./widgets/WalkthroughWidget";
import { StatsWidget } from "./widgets/StatsWidget";
import { GlobalTemplateWidget } from "./widgets/GlobalTemplateWidget";
import { ProgramNameWidget } from "./widgets/ProgramNameWidget";
import { AiBuildWidget } from "./widgets/AiBuildWidget";
import { LowerThirdWidget } from "./widgets/LowerThirdWidget";
import { OPTIONAL_BEATS, isOptionalBeat } from "./beatCatalog";
import { sectionLabel } from "./sectionLabels";
import type { ProgramSpec } from "./types";

export function BeatList() {
  const { effectiveSpec, dispatch, fullEdit } = useBeatEditor();
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

  // Reorder: swap the beat at `idx` with its neighbour, dispatch the full
  // new order (coalesces to one buffer slot).
  const moveBeat = (idx: number, dir: -1 | 1) => {
    const j = idx + dir;
    if (j < 0 || j >= beats.length) return;
    const order = beats.map((b) => b.id);
    [order[idx], order[j]] = [order[j], order[idx]];
    dispatch({ type: "APPEND_OP", op: { op: "set-beat-order", order } });
  };

  const removeBeat = (beatId: string) =>
    dispatch({ type: "APPEND_OP", op: { op: "remove-beat", beatId } });

  const addableBeats = OPTIONAL_BEATS.filter((def) => !beats.some((b) => b.id === def.id));

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
      {beats.map((b, idx) => {
        const startSec = cursor;
        const endSec = cursor + b.seconds;
        cursor += b.seconds;
        return (
          // Anchor so the left-nav beat sub-items can scroll to a beat.
          <div key={b.id} id={`beat-${b.id}`} className="scroll-mt-2">
            <BeatCard
              beatId={b.id}
              kind={b.kind}
              startSec={startSec}
              endSec={endSec}
              collapsed={collapsedIds.has(b.id)}
              onToggleCollapsed={() => toggleOne(b.id)}
              // Structural controls only in the template editor (fullEdit).
              structural={
                fullEdit
                  ? {
                      removable: isOptionalBeat(b.id),
                      canMoveUp: idx > 0,
                      canMoveDown: idx < beats.length - 1,
                      onMoveUp: () => moveBeat(idx, -1),
                      onMoveDown: () => moveBeat(idx, 1),
                      onRemove: () => removeBeat(b.id),
                    }
                  : undefined
              }
            >
              <NarrationWidget beatId={b.id} />
              {renderKindBody(b.id, b.kind, effectiveSpec, fullEdit)}
            </BeatCard>
          </div>
        );
      })}

      {fullEdit && addableBeats.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-dashed p-3">
          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Add beat
          </span>
          {addableBeats.map((def) => (
            <button
              key={def.id}
              type="button"
              onClick={() => dispatch({ type: "APPEND_OP", op: { op: "add-beat", beatId: def.id } })}
              className="inline-flex items-center gap-1 rounded border bg-background px-2 py-1 text-xs hover:border-primary"
            >
              <Plus className="h-3.5 w-3.5" />
              {sectionLabel(def.id).name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function renderKindBody(beatId: string, kind: string, spec: ProgramSpec, fullEdit: boolean) {
  if (kind === "body_scene") {
    return (
      <>
        {fullEdit && <LowerThirdWidget beatId={beatId} />}
        {(spec.scene?.clips ?? []).map((_, i) => (
          <ClipSlotWidget key={i} beatId={beatId} clipKind="scene-clip" index={i} />
        ))}
      </>
    );
  }
  if (kind === "body_product_beats") {
    return (spec.product?.beats ?? []).map((_, i) => (
      <ClipSlotWidget key={i} beatId={beatId} clipKind="product-beat" index={i} />
    ));
  }
  if (kind === "body_ai_build") {
    // The card content (headline/chips/subhead) is editable only in the
    // template editor; the workbench has no backend op for it.
    return fullEdit ? <AiBuildWidget beatId={beatId} /> : <GlobalTemplateWidget beatId={beatId} kind={kind} />;
  }
  if (kind === "body_problem_stat") {
    return <StatsWidget beatId={beatId} path="problem" />;
  }
  if (kind === "body_impact_stats") {
    return (spec.impact ?? []).map((_, i) => (
      <StatsWidget key={i} beatId={beatId} path={`impact[${i}]`} />
    ));
  }
  if (kind === "intro_handoff") {
    // The handoff card edits spec.name, not anything in the global
    // template — different concept, different drawer.
    return <ProgramNameWidget beatId={beatId} />;
  }
  if (kind === "body_walkthrough") {
    // Walkthrough arc: each section plays a range of one master clip with
    // a lower-third. Narration is already rendered above by BeatList.
    return <WalkthroughWidget beatId={beatId} />;
  }
  if (kind === "intro_title" || kind === "outro_card") {
    // Walkthrough title / end cards carry only their voiceover (already
    // rendered above). No extra per-beat content to configure here.
    return null;
  }
  return <GlobalTemplateWidget beatId={beatId} kind={kind} />;
}
