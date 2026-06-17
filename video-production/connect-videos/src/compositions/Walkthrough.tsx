import { AbsoluteFill, Video, staticFile, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { Lower3rd } from "../components/Lower3rd";
import type { ProgramSpec, WalkthroughBeat } from "../lib/spec";

/**
 * One walkthrough section of the connect-walkthrough arc. Plays a RANGE
 * of one master clip full-bleed (objectFit: cover, `startFrom` honoring
 * the beat's start_seconds in the source), overlays a single
 * lower-third, and lets the top-level CaptionBar + per-beat VO ride on
 * top.
 *
 * The beat's on-screen DURATION is the Sequence length given to it by
 * Root.tsx (b.durationFrames) — i.e. the beat's `seconds` from the
 * spec's `beats:` list. `start_seconds` is purely the IN-point into the
 * master clip. (The spec's per-walkthrough `duration_seconds` is the
 * authored selection window — bookkeeping that lines up with the beat
 * seconds; the renderer plays exactly the Sequence length regardless.)
 */
export const Walkthrough: React.FC<{ wt: WalkthroughBeat }> = ({ wt }) => {
  const { fps } = useVideoConfig();
  const src = wt.asset.startsWith("http") ? wt.asset : staticFile(wt.asset);
  const startFrom = Math.round((wt.start_seconds ?? 0) * fps);
  return (
    <AbsoluteFill style={{ background: theme.colors.foreground }}>
      <Video
        src={src}
        startFrom={startFrom}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
        onError={() => {
          /* Missing asset — render blank; drop the real file in the cache to fix */
        }}
      />
      <Lower3rd text={wt.lower_third} />
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
