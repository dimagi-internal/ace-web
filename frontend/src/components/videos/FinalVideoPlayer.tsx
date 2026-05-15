import { useState } from "react";
import { useBeatEditor } from "./BeatEditorContext";

// Renders the final.mp4 if one exists, else collapses to a thin "no
// render yet" placeholder so an unrendered run doesn't dominate the
// editor with a giant black box. The <video> element fires `onError`
// the moment the src returns 404, which is our cue to swap UIs.
export function FinalVideoPlayer() {
  const { workspaceSlug, programSlug, runId } = useBeatEditor();
  const [hasOutput, setHasOutput] = useState<boolean>(true);
  const src = `/api/w/${workspaceSlug}/videos/programs/${programSlug}/runs/${runId}/media/final.mp4`;

  if (!hasOutput) {
    return (
      <div className="flex items-center gap-3 rounded-md border border-dashed bg-muted/10 px-4 py-3 text-sm text-muted-foreground">
        <span aria-hidden>🎬</span>
        <span>
          No render yet for this run — click <strong className="text-foreground">Re-render</strong> to generate the first draft.
        </span>
      </div>
    );
  }

  return (
    <div className="w-full">
      <video
        id="final-video"
        controls
        preload="metadata"
        className="w-full rounded-md border bg-black"
        src={src}
        onError={() => setHasOutput(false)}
      />
    </div>
  );
}
