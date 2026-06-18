import { AbsoluteFill, Freeze, Video, staticFile, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { Lower3rd } from "../components/Lower3rd";
import type { ProgramSpec, WalkthroughBeat } from "../lib/spec";

/**
 * One walkthrough section of the connect-ddd-walkthrough arc. Plays a RANGE
 * of one master clip full-bleed (objectFit: cover, `startFrom` honoring
 * the beat's start_seconds in the source), overlays a single
 * lower-third, and lets the top-level CaptionBar + per-beat VO ride on
 * top.
 *
 * The beat's on-screen DURATION is the Sequence length given to it by
 * Root.tsx (b.durationFrames) — i.e. the beat's `seconds` from the
 * spec's `beats:` list, which the audio-aligner STRETCHES to fit the
 * narration. `start_seconds` is the IN-point into the master clip and
 * `duration_seconds` is how long the selected RANGE of footage runs.
 *
 * HOLD-LAST-FRAME: when the beat's on-screen length (durationInFrames)
 * runs LONGER than the selected range (duration_seconds), the clip would
 * otherwise keep playing past its range into the NEXT section's footage
 * (drift). We wrap the <Video> in <Freeze> so it plays only its range
 * [start_seconds, start_seconds + duration_seconds] and then freezes on
 * the last frame of that range for the remaining beat time — the section
 * stays on its own footage while the narration finishes.
 *
 * When duration_seconds is absent there's no defined range, so we fall
 * back to playing the whole beat (the original behavior).
 */
/**
 * Decide whether to hold the last frame and, if so, at which range frame.
 *
 * Returns the range length in frames when the beat's on-screen length
 * (`beatFrames`) runs LONGER than the selected range (`durationSeconds`)
 * — i.e. when footage would otherwise drift into the next section.
 * Returns null (play the whole beat unchanged) when `durationSeconds` is
 * absent or the range is at least as long as the beat.
 */
export function freezeRangeFrames(
  durationSeconds: number | undefined,
  fps: number,
  beatFrames: number
): number | null {
  if (durationSeconds == null) return null;
  const rangeFrames = Math.max(1, Math.round(durationSeconds * fps));
  return rangeFrames < beatFrames ? rangeFrames : null;
}

export const Walkthrough: React.FC<{ wt: WalkthroughBeat }> = ({ wt }) => {
  const { fps, durationInFrames } = useVideoConfig();
  const src = wt.asset.startsWith("http") ? wt.asset : staticFile(wt.asset);
  const startFrom = Math.round((wt.start_seconds ?? 0) * fps);

  const video = (
    <Video
      src={src}
      startFrom={startFrom}
      style={{ width: "100%", height: "100%", objectFit: "cover" }}
      onError={() => {
        /* Missing asset — render blank; drop the real file in the cache to fix */
      }}
    />
  );

  // The selected range, in frames, when shorter than the on-screen beat.
  const rangeFrames = freezeRangeFrames(wt.duration_seconds, fps, durationInFrames);
  const shouldFreeze = rangeFrames != null;

  return (
    <AbsoluteFill style={{ background: theme.colors.foreground }}>
      {shouldFreeze ? (
        // active while we're past the end of the range: pin to the range's
        // last frame (rangeFrames - 1, relative to the Video's own
        // startFrom-offset timeline) so the footage holds instead of
        // bleeding into the next section.
        <Freeze frame={rangeFrames - 1} active={(f) => f >= rangeFrames}>
          {video}
        </Freeze>
      ) : (
        video
      )}
      {wt.lower_third ? <Lower3rd text={wt.lower_third} /> : null}
    </AbsoluteFill>
  );
};

/** Lookup helper — resolve a beat id to its walkthrough entry. */
export function walkthroughForBeat(
  spec: ProgramSpec,
  beatId: string
): WalkthroughBeat | undefined {
  return spec.walkthrough?.[beatId];
}
