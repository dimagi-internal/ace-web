import { Composition, AbsoluteFill, Sequence, registerRoot } from "remotion";
import { parseProgramSpec, applyManifestRefs, type ProgramSpec } from "./lib/spec";
import { parseDefaults, resolveBeats, type ResolvedBeat } from "./lib/beats";
import { Intro } from "./compositions/Intro";
import { ProgramBody } from "./compositions/ProgramBody";
import { Outro } from "./compositions/Outro";
import { CaptionBar } from "./components/CaptionBar";
import defaultsYaml from "../programs/_defaults.yaml";
import mbwYaml from "../programs/mbw.yaml";
import chcYaml from "../programs/chc.yaml";

interface VideoProps {
  programSlug: string;
  captions?: { startFrame: number; endFrame: number; text: string }[];
}

// Programs registered for Studio preview. Add new entries here as program
// YAMLs land in `programs/`. The render CLI loads YAML by slug from disk
// (Node side) so this registry only matters for in-browser Studio preview.
const PROGRAMS_REGISTRY: Record<string, string> = {
  mbw: mbwYaml,
  chc: chcYaml,
};

const defaults = parseDefaults(defaultsYaml);

const ProgramVideo: React.FC<VideoProps> = ({ programSlug, captions = [] }) => {
  const yamlText = PROGRAMS_REGISTRY[programSlug];
  if (!yamlText) {
    throw new Error(
      `Unknown program slug "${programSlug}". Register its YAML in src/Root.tsx PROGRAMS_REGISTRY.`
    );
  }
  const spec: ProgramSpec = applyManifestRefs(parseProgramSpec(yamlText));
  const timeline = resolveBeats(defaults, spec.beat_overrides ?? {});
  const byId = Object.fromEntries(timeline.beats.map((b) => [b.id, b])) as Record<
    string,
    ResolvedBeat
  >;
  const introBeats = {
    hook: byId.hook.durationFrames,
    cycle: byId.cycle.durationFrames,
    handoff: byId.handoff.durationFrames,
  };
  const bodyBeats = timeline.beats.filter((b) => b.kind.startsWith("body_"));
  const outroBeat = byId.cta;

  return (
    <AbsoluteFill>
      <Sequence durationInFrames={byId.handoff.startFrame + byId.handoff.durationFrames}>
        <Intro programName={spec.name} beatFrames={introBeats} />
      </Sequence>
      <Sequence
        from={bodyBeats[0].startFrame}
        durationInFrames={
          bodyBeats[bodyBeats.length - 1].startFrame +
          bodyBeats[bodyBeats.length - 1].durationFrames -
          bodyBeats[0].startFrame
        }
      >
        <ProgramBody spec={spec} bodyBeats={bodyBeats} />
      </Sequence>
      <Sequence from={outroBeat.startFrame} durationInFrames={outroBeat.durationFrames}>
        <Outro programUrl={spec.program_url} />
      </Sequence>
      {captions.map((c, i) => (
        <Sequence key={i} from={c.startFrame} durationInFrames={c.endFrame - c.startFrame}>
          <CaptionBar text={c.text} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

export const RemotionRoot: React.FC = () => {
  const defaultSlug = "mbw";
  const spec = applyManifestRefs(parseProgramSpec(PROGRAMS_REGISTRY[defaultSlug]));
  const timeline = resolveBeats(defaults, spec.beat_overrides ?? {});
  return (
    <Composition
      id="ProgramVideo"
      component={ProgramVideo as unknown as React.FC<Record<string, unknown>>}
      durationInFrames={timeline.totalFrames}
      fps={timeline.fps}
      width={1920}
      height={1080}
      defaultProps={{ programSlug: defaultSlug, captions: [] }}
    />
  );
};

registerRoot(RemotionRoot);
