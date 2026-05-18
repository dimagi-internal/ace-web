import { Composition, AbsoluteFill, Sequence, registerRoot } from "remotion";
import { parseProgramSpec, applyManifestRefs, type ProgramSpec } from "./lib/spec";
import { parseDefaults, resolveBeats, type ResolvedBeat } from "./lib/beats";
import { Intro } from "./compositions/Intro";
import { ProgramBody } from "./compositions/ProgramBody";
import { Outro } from "./compositions/Outro";
import { CaptionBar } from "./components/CaptionBar";
import defaultsYaml from "../programs/_defaults.yaml";
// Programs now live as ``programs/<slug>/runs/run-NNN/spec.yaml`` (mirrors
// ace-web's opp/run model). Studio preview pins to run-001 of each program
// — the render CLI passes the spec via props at render time, so this
// registry only matters for in-browser preview.
import mbwYaml from "../programs/mbw/runs/run-001/spec.yaml";
import chcYaml from "../programs/chc/runs/run-001/spec.yaml";

interface VideoProps {
  programSlug: string;
  /**
   * Raw spec.yaml text. The render CLI (scripts/render.ts) loads the
   * spec from disk and passes it through verbatim so any program slug
   * works without a Root.tsx registry update. Studio preview omits
   * this and falls back to PROGRAMS_REGISTRY for the bundled programs.
   */
  specYaml?: string;
  /**
   * Per-beat duration overrides computed by the render CLI from the
   * actual synthesized audio (see render.ts::realignTimelineToAudio).
   * Merged with spec.beat_overrides before resolveBeats so the visual
   * track matches the mux step's per-beat audio placement. Studio
   * preview omits this — preview uses spec.beat_overrides as-is.
   */
  beatOverrides?: Record<string, { seconds?: number }>;
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
// Brand strings live in _defaults.yaml — single source of truth.
// Fallback values match what was hardcoded before the brand section
// was introduced, so older defaults files still render.
const BRAND_FALLBACK = {
  tagline: "Pay for verified service delivery, not planned activity.",
  cycleSteps: ["Learn", "Deliver", "Verify", "Pay"] as const,
};
const brand = defaults.brand
  ? {
      tagline: defaults.brand.tagline,
      cycleSteps: defaults.brand.cycle_steps as readonly [string, string, string, string],
    }
  : BRAND_FALLBACK;

const ProgramVideo: React.FC<VideoProps> = ({
  programSlug,
  specYaml,
  beatOverrides,
  captions = [],
}) => {
  // Render-CLI path: spec passed verbatim via props. Studio-preview
  // path: look up the slug in the bundled registry. The render CLI
  // wins so new programs created via /ace:video-from-program-page
  // render immediately without a registry edit.
  const yamlText = specYaml ?? PROGRAMS_REGISTRY[programSlug];
  if (!yamlText) {
    throw new Error(
      `Unknown program slug "${programSlug}" and no specYaml prop provided. ` +
        `For Studio preview, register the YAML in src/Root.tsx PROGRAMS_REGISTRY; ` +
        `for the render CLI, ensure scripts/render.ts passes specYaml in props.`
    );
  }
  const spec: ProgramSpec = applyManifestRefs(parseProgramSpec(yamlText));
  // Merge: per-prop overrides (from render-CLI's audio-alignment pass)
  // win over spec.beat_overrides win over defaults.
  const mergedOverrides = { ...(spec.beat_overrides ?? {}), ...(beatOverrides ?? {}) };
  const timeline = resolveBeats(defaults, mergedOverrides);
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
        <Intro
          programName={spec.name}
          brand={brand}
          beatFrames={introBeats}
          // Cycle highlight syncs to the keyword positions in this
          // beat's narration ("learn"/"deliver"/"verif"/"pay") so the
          // ring lights up the right step as the voiceover names it.
          cycleNarration={spec.narration?.by_beat?.cycle}
        />
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
