import { AbsoluteFill, Sequence, Video, staticFile, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { Lower3rd } from "../components/Lower3rd";
import { KenBurns } from "../components/KenBurns";
import { StatCard } from "../components/StatCard";
import { AiBuildCard } from "../components/AiBuildCard";
import { AppScreen } from "../components/AppScreen";
import { Walkthrough } from "./Walkthrough";
import {
  asResolvedClip,
  distributeClipDurations,
  type ProgramSpec,
} from "../lib/spec";
import type { ResolvedBeat } from "../lib/beats";

interface Props {
  spec: ProgramSpec;
  bodyBeats: ResolvedBeat[]; // ai_build, scene, problem, product, impact (order from defaults)
}

const isVideo = (s: string) => /\.(mp4|webm|mov)$/i.test(s);

const Scene: React.FC<{ spec: ProgramSpec; durationFrames: number }> = ({
  spec,
  durationFrames,
}) => {
  const { fps } = useVideoConfig();
  const totalSec = durationFrames / fps;
  // scene is optional (walkthrough specs omit it); the body_scene beat is
  // never in a walkthrough timeline, so this guard is defensive only.
  if (!spec.scene) return null;
  const clips = spec.scene.clips.map(asResolvedClip);
  const durations = distributeClipDurations(clips, totalSec);
  let cursor = 0;
  return (
    <AbsoluteFill style={{ background: theme.colors.foreground }}>
      {clips.map((clip, i) => {
        const startFrame = Math.round(cursor * fps);
        const lengthFrames = Math.max(1, Math.round(durations[i] * fps));
        cursor += durations[i];
        const src = clip.asset.startsWith("http") ? clip.asset : staticFile(clip.asset);
        const startFrom = Math.round(clip.start_seconds * fps);
        return (
          <Sequence key={i} from={startFrame} durationInFrames={lengthFrames}>
            {isVideo(clip.asset) ? (
              <AbsoluteFill>
                <Video
                  src={src}
                  startFrom={startFrom}
                  style={{ width: "100%", height: "100%", objectFit: "cover" }}
                  onError={() => {
                    /* Missing asset — render blank; drop real file in cache to fix */
                  }}
                />
              </AbsoluteFill>
            ) : (
              <KenBurns src={src} durationFrames={lengthFrames} />
            )}
          </Sequence>
        );
      })}
      <Lower3rd text={spec.scene.lower_third} />
    </AbsoluteFill>
  );
};

const ProductBeats: React.FC<{ spec: ProgramSpec; durationFrames: number }> = ({
  spec,
  durationFrames,
}) => {
  const { fps } = useVideoConfig();
  const totalSec = durationFrames / fps;
  // product is optional (walkthrough specs omit it); the
  // body_product_beats beat is never in a walkthrough timeline, so this
  // guard is defensive only.
  if (!spec.product) return null;
  // Reuse the same distribution helper by mapping product beats into a
  // ResolvedClipRef-shaped array.
  const refs = spec.product.beats.map((b) => ({
    asset: b.asset,
    start_seconds: b.start_seconds ?? 0,
    duration_seconds: b.duration_seconds,
  }));
  const durations = distributeClipDurations(refs, totalSec);
  let cursor = 0;
  return (
    <AbsoluteFill style={{ background: theme.colors.background }}>
      {spec.product.beats.map((b, i) => {
        const startFrame = Math.round(cursor * fps);
        const lengthFrames = Math.max(1, Math.round(durations[i] * fps));
        cursor += durations[i];
        return (
          <Sequence key={i} from={startFrame} durationInFrames={lengthFrames}>
            <AppScreen
              asset={b.asset}
              caption={b.caption}
              startSeconds={b.start_seconds ?? 0}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

const ImpactStats: React.FC<{ spec: ProgramSpec; durationFrames: number }> = ({
  spec,
  durationFrames,
}) => {
  // Explainer-mode specs omit `impact`; the body_impact_stats beat is
  // filtered out of the timeline upstream (Root.tsx::filterDefaultsForSpec)
  // so this normally isn't reached when impact is absent — guard anyway
  // so the optional type is satisfied and a stray beat renders nothing.
  const impact = spec.impact;
  if (!impact || impact.length === 0) return null;
  const slot = Math.floor(durationFrames / impact.length);
  return (
    <AbsoluteFill>
      {impact.map((s, i) => (
        <Sequence key={i} from={i * slot} durationInFrames={slot}>
          <StatCard big={s.big} caption={s.caption} source={s.source} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

export const ProgramBody: React.FC<Props> = ({ spec, bodyBeats }) => {
  const bodyStart = bodyBeats[0].startFrame;
  const renderBeat = (b: ResolvedBeat) => {
    switch (b.kind) {
      case "body_ai_build":
        // The program-designer AI cut. The beat is filtered out upstream
        // for the standard cut / specs without ai_build, but guard so the
        // optional type is satisfied and a stray beat renders nothing.
        if (!spec.ai_build) return null;
        return (
          <AiBuildCard
            headline={spec.ai_build.headline}
            components={spec.ai_build.components}
            subhead={spec.ai_build.subhead}
          />
        );
      case "body_scene":
        return <Scene spec={spec} durationFrames={b.durationFrames} />;
      case "body_problem_stat":
        // Explainer-mode specs omit `problem`; the beat is filtered out
        // upstream, but guard so the optional type is satisfied.
        if (!spec.problem) return null;
        return (
          <StatCard
            big={spec.problem.big}
            caption={spec.problem.caption}
            source={spec.problem.source}
          />
        );
      case "body_product_beats":
        return <ProductBeats spec={spec} durationFrames={b.durationFrames} />;
      case "body_impact_stats":
        return <ImpactStats spec={spec} durationFrames={b.durationFrames} />;
      case "body_walkthrough": {
        // connect-ddd-walkthrough: one master-clip range full-bleed +
        // lower-third, keyed by this beat's id. The superRefine
        // guarantees the entry exists for a body_walkthrough beat; guard
        // so the optional type is satisfied and a stray beat renders
        // nothing.
        const wt = spec.walkthrough?.[b.id];
        if (!wt) return null;
        return <Walkthrough wt={wt} />;
      }
      default:
        return null;
    }
  };
  return (
    <>
      {bodyBeats.map((b) => (
        <Sequence
          key={b.id}
          from={b.startFrame - bodyStart}
          durationInFrames={b.durationFrames}
        >
          {renderBeat(b)}
        </Sequence>
      ))}
    </>
  );
};
