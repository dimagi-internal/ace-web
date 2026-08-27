import { BeatEditorProvider } from "./BeatEditorContext";
import { BeatEditorTopBar } from "./BeatEditorTopBar";
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
  // When provided, replaces the default submitEditBatch + getVideoRun save
  // flow. Called with the fully-applied spec; caller owns the write.
  // On success, the buffer is cleared and the "Saved" state is shown.
  onSave?: (effectiveSpec: ProgramSpec) => Promise<void>;
}

export function BeatEditor({
  workspaceSlug, programSlug, runId, spec, onSpecRefetched, onRerender, onSave,
}: Props) {
  return (
    <BeatEditorProvider
      workspaceSlug={workspaceSlug}
      programSlug={programSlug}
      runId={runId}
      spec={spec}
      onSave={onSave}
    >
      {/* The bulky editor lives in the workbench center pane: the save/
          re-render TopBar, the rendered video, the beat list, and the
          on-demand EditDrawer overlay. Program/run navigation is the
          page's left rail (VideoNavRail), not here. */}
      <div className="flex flex-col gap-4 p-4">
        <BeatEditorTopBar onSpecRefetched={onSpecRefetched} onRerender={onRerender} />
        <FinalVideoPlayer />
        <BeatList />
      </div>
      <EditDrawer />
    </BeatEditorProvider>
  );
}
