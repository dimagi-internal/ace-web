import { useBeatEditor } from "./BeatEditorContext";

export function FinalVideoPlayer() {
  const { workspaceSlug, programSlug, runId } = useBeatEditor();
  const src = `/api/w/${workspaceSlug}/videos/programs/${programSlug}/runs/${runId}/media/final.mp4`;
  return (
    <div className="w-full">
      <video
        id="final-video"
        controls
        preload="metadata"
        className="w-full rounded-md border bg-black"
        src={src}
      />
    </div>
  );
}
