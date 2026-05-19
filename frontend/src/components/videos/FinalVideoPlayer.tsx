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
  //
  // The overlay used to be a `pointer-events-none` div that relied on
  // the wrapper's onClick to call `play()`. That caused a frustrating
  // bug: clicks passed through to the video element, the native handler
  // briefly toggled state in a way that fired `onPlay` (hiding the
  // overlay) but ended with the video still paused, so the user had to
  // click the native lower-left button anyway. Now the overlay IS the
  // button — captures the click itself, calls play(), and stops
  // propagation so nothing else fires. The native controls still work
  // independently once playback starts.
  const handlePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    void v.play().then(
      () => setHasPlayed(true),
      // play() can reject if the browser blocks autoplay (rare for a
      // user-initiated click, but happens with muted autoplay policies
      // or rapid clicks). In that case we leave the overlay visible so
      // the user can try again instead of staring at a black box.
      () => {},
    );
  };

  return (
    <div className="relative mx-auto w-full max-w-3xl">
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
        onPause={() => {
          // If something pauses the video (e.g. the click sequence
          // briefly toggles it), bring the overlay back so the play
          // affordance is always visible when the video isn't playing.
          // Without this, a user who pauses mid-video sees only the
          // native controls fade — easy to think the player is broken.
          if (videoRef.current && videoRef.current.currentTime === 0) {
            setHasPlayed(false);
          }
        }}
      />
      {!hasPlayed && (
        // Centered, button-sized — NOT inset-0. The previous full-bleed
        // version covered the native controls strip at the bottom of
        // the video, so users trying to drag the seek bar before first
        // play hit the overlay button instead and the video would just
        // start from currentTime=0. Now the overlay is a single round
        // affordance over the visual middle of the player; the native
        // scrubber / volume / fullscreen controls along the bottom are
        // always reachable. `top-1/2 left-1/2 -translate-*` centers it
        // without claiming the whole frame.
        <button
          type="button"
          aria-label="Play video"
          onClick={(e) => {
            e.stopPropagation();
            handlePlay();
          }}
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-black/55 p-4 text-white opacity-90 shadow-lg backdrop-blur-sm transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-white/60"
        >
          <svg width="36" height="36" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
        </button>
      )}
    </div>
  );
}
