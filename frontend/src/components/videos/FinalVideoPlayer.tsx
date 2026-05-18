import { useRef, useState } from "react";
import { useBeatEditor } from "./BeatEditorContext";

// Renders the final.mp4 if one exists, else collapses to a thin "no
// render yet" placeholder so an unrendered run doesn't dominate the
// editor with a giant black box. The <video> element fires `onError`
// the moment the src returns 404, which is our cue to swap UIs.
export function FinalVideoPlayer() {
  const { workspaceSlug, programSlug, runId } = useBeatEditor();
  const [hasOutput, setHasOutput] = useState<boolean>(true);
  const [hasPlayed, setHasPlayed] = useState<boolean>(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  // Prefix every API URL with BASE_URL (production puts ace-web behind a
  // `/ace/*` ALB tenant path; Vite proxies the same prefix locally).
  // Without this, a bare `/api/...` only works through Vite's optional
  // bare-prefix fallback proxy — fine locally, 404 in prod.
  const prefix = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const src = `${prefix}/api/w/${workspaceSlug}/videos/programs/${programSlug}/runs/${runId}/media/final.mp4`;

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

  // The Remotion-rendered intro starts on a black frame, so the
  // browser's first paint of the <video> is solid black with no visual
  // signal that it's interactive. `aspect-video` caps the player height
  // (was full-bleed) so the beat list is visible above the fold, and a
  // play-overlay ring tells the user this is clickable. The native
  // `controls` bar remains the source of truth for playback.
  return (
    <div
      className="relative mx-auto w-full max-w-3xl cursor-pointer"
      onClick={() => {
        const v = videoRef.current;
        if (!v) return;
        if (v.paused) {
          void v.play();
        }
      }}
    >
      <video
        ref={videoRef}
        id="final-video"
        controls
        preload="metadata"
        playsInline
        className="aspect-video w-full rounded-md border bg-black"
        src={src}
        onError={() => setHasOutput(false)}
        onPlay={() => setHasPlayed(true)}
      />
      {!hasPlayed && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 flex items-center justify-center"
        >
          <div className="rounded-full bg-black/50 p-4 text-white opacity-80 backdrop-blur-sm">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
          </div>
        </div>
      )}
    </div>
  );
}
