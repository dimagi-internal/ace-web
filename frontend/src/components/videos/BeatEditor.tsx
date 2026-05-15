import { BeatEditorProvider } from "./BeatEditorContext";
import { BeatEditorTopBar } from "./BeatEditorTopBar";
import { TimelineStrip } from "./TimelineStrip";
import { FinalVideoPlayer } from "./FinalVideoPlayer";
import { BeatList } from "./BeatList";
import { EditDrawer } from "./drawer/EditDrawer";
import type { ProgramSpec } from "./types";

interface Props {
  workspaceSlug: string;
  programSlug: string;
  runId: string;
  spec: ProgramSpec;
  // Bubbles to the page so the Re-render button can refetch if needed.
  onSpecRefetched?: (spec: ProgramSpec) => void;
  // Called from the TopBar's post-save Re-render CTA. Optional — when
  // omitted, the CTA hides.
  onRerender?: () => void;
}

export function BeatEditor({
  workspaceSlug, programSlug, runId, spec, onSpecRefetched, onRerender,
}: Props) {
  return (
    <BeatEditorProvider
      workspaceSlug={workspaceSlug}
      programSlug={programSlug}
      runId={runId}
      spec={spec}
    >
      <div className="flex flex-col gap-4">
        <BeatEditorTopBar onSpecRefetched={onSpecRefetched} onRerender={onRerender} />
        <TimelineStrip />
        <FinalVideoPlayer />
        <BeatList />
        <EditDrawer />
      </div>
    </BeatEditorProvider>
  );
}
