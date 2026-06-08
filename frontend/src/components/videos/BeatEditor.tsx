import { BeatEditorProvider } from "./BeatEditorContext";
import { BeatEditorTopBar } from "./BeatEditorTopBar";
import { FinalVideoPlayer } from "./FinalVideoPlayer";
import { BeatList } from "./BeatList";
import { EditDrawer } from "./drawer/EditDrawer";
import { WorkbenchLayout, usePaneCollapsed } from "../workbench";
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
  const beats = usePaneCollapsed("ace.video.beatsCollapsed");
  return (
    <BeatEditorProvider
      workspaceSlug={workspaceSlug}
      programSlug={programSlug}
      runId={runId}
      spec={spec}
    >
      {/* Same three-pane workbench shell the opp run-view uses: the beat
          outline is the left navigator, the rendered video is the center
          canvas, and EditDrawer overlays on the right when a beat widget is
          opened. */}
      <WorkbenchLayout
        header={
          <BeatEditorTopBar onSpecRefetched={onSpecRefetched} onRerender={onRerender} />
        }
        left={{
          title: "Beats",
          collapsed: beats.collapsed,
          onToggle: beats.toggle,
          expandedWidth: 480,
          content: (
            <div className="p-3">
              <BeatList />
            </div>
          ),
        }}
        center={
          <div className="p-4">
            <FinalVideoPlayer />
          </div>
        }
      />
      <EditDrawer />
    </BeatEditorProvider>
  );
}
