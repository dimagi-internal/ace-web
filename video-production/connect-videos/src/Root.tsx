import { Composition, AbsoluteFill, Sequence, registerRoot } from "remotion";
import { parseProgramSpec, applyManifestRefs, type ProgramSpec } from "./lib/spec";
import { parseDefaults, resolveBeats, effectiveBeatsForSpec, type ResolvedBeat } from "./lib/beats";
import { Intro, TitleCard } from "./compositions/Intro";
import { ProgramBody } from "./compositions/ProgramBody";
import { Outro } from "./compositions/Outro";
import { CaptionBar } from "./components/CaptionBar";
import { ProspectBranding } from "./components/ProspectBranding";
import defaultsYaml from "../programs/global_style.yaml";
// Programs now live as ``programs/<slug>/runs/run-NNN/spec.yaml`` (mirrors
// ace-web's opp/run model). Studio preview pins to run-001 of each program
// — the render CLI passes the spec via props at render time, so this
// registry only matters for in-browser preview.
import mbwYaml from "../programs/mbw/runs/run-001/spec.yaml";

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
  /**
   * Exact seconds-into-cycle-audio for each cycle keyword, extracted
   * from the ElevenLabs alignment data at render time. When present,
   * the Intro/Cycle component switches the highlight on the spoken
   * word; when absent, falls back to the word-index proportional
   * estimate. Studio preview omits this (no audio synth).
   */
  cycleStepStartSeconds?: {
    learn?: number;
    deliver?: number;
    verify?: number;
    pay?: number;
  };
}

// Programs registered for Studio preview. Add new entries here as program
// YAMLs land in `programs/`. The render CLI loads YAML by slug from disk
// (Node side) so this registry only matters for in-browser Studio preview.
const PROGRAMS_REGISTRY: Record<string, string> = {
  mbw: mbwYaml,
};

const defaults = parseDefaults(defaultsYaml);
// Global-template strings live in global_style.yaml under
// `global_template:` — single source of truth at the template level.
// Programs may override individual fields by setting
// `global_template.tagline` and/or `global_template.cycle_steps` on
// their own spec.yaml (written when the user clicks "Edit override"
// on a GLOBAL TEMPLATE panel in ace-web's video editor).
//
// Renamed from `brand:` 2026-05-21. Legacy `brand:` reads are kept as
// a fallback so any spec.yaml that hasn't been migrated still
// renders. The fallback constant ships hardcoded defaults so even an
// global_style.yaml that's missing the section renders.
const GLOBAL_TEMPLATE_FALLBACK = {
  tagline: "Pay for verified service delivery, not planned activity.",
  cycleSteps: ["Learn", "Deliver", "Verify", "Pay"] as const,
};
function resolveGlobalTemplate(spec: ProgramSpec): {
  tagline: string;
  cycleSteps: readonly [string, string, string, string];
} {
  const specOverride = (
    spec as {
      global_template?: { tagline?: string; cycle_steps?: readonly string[] };
      brand?: { tagline?: string; cycle_steps?: readonly string[] };
    }
  );
  const specGlobal = specOverride.global_template ?? specOverride.brand;
  const defaultsGlobal = defaults.global_template ?? defaults.brand;
  const base = defaultsGlobal
    ? {
        tagline: defaultsGlobal.tagline,
        // cycle_steps is z.array(z.string()).length(4) — runtime-guaranteed 4
        // but inferred as string[]; narrow via readonly string[] (same idiom as
        // the spec-override branch below) so tsc accepts the tuple cast.
        cycleSteps: defaultsGlobal.cycle_steps as readonly string[] as readonly [
          string,
          string,
          string,
          string,
        ],
      }
    : GLOBAL_TEMPLATE_FALLBACK;
  const tagline = specGlobal?.tagline ?? base.tagline;
  const cycleSteps = (specGlobal?.cycle_steps && specGlobal.cycle_steps.length === 4
    ? (specGlobal.cycle_steps as readonly [string, string, string, string])
    : base.cycleSteps);
  return { tagline, cycleSteps };
}

const ProgramVideo: React.FC<VideoProps> = ({
  programSlug,
  specYaml,
  beatOverrides,
  captions = [],
  cycleStepStartSeconds,
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
  // Global template is resolved per-render so spec.global_template
  // overrides are picked up (renderer doesn't restart between renders
  // in Studio preview).
  const brand = resolveGlobalTemplate(spec);
  // Merge: per-prop overrides (from render-CLI's audio-alignment pass)
  // win over spec.beat_overrides win over defaults.
  const mergedOverrides = { ...(spec.beat_overrides ?? {}), ...(beatOverrides ?? {}) };
  // Explainer mode: drop the problem/impact stat beats from the global
  // timeline when this spec omits the matching field, recomputing
  // total_seconds so resolveBeats' sum invariant still holds.
  const effectiveDefaults = effectiveBeatsForSpec(defaults, spec);
  const timeline = resolveBeats(effectiveDefaults, mergedOverrides);

  // Arc selection by beat kind. The connect-walkthrough explainer arc is
  // detected by ANY intro_title / body_walkthrough / outro_card beat (it
  // can only come from a spec that carries its own `beats:` list, since
  // those kinds never appear in the shared global_style.yaml timeline).
  // Everything else — the 60s marketing arc AND main's connect-explainer
  // (which rides the same intro_hook/cycle/handoff + body_* + outro_cta
  // arc) — renders unchanged through renderMarketing. This is the single
  // switch; the shared global_style.yaml defaults are never touched.
  const isWalkthrough = timeline.beats.some(
    (b) => b.kind === "intro_title" || b.kind === "body_walkthrough" || b.kind === "outro_card",
  );

  return (
    <AbsoluteFill>
      {isWalkthrough
        ? renderWalkthrough(spec, timeline.beats)
        : renderMarketing(spec, brand, timeline, cycleStepStartSeconds)}
      {captions.map((c, i) => (
        <Sequence key={i} from={c.startFrame} durationInFrames={c.endFrame - c.startFrame}>
          <CaptionBar text={c.text} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

/**
 * Marketing arc (60s campaign overview AND connect-explainer). Hard-pulls
 * the fixed hook/cycle/handoff + cta beats, exactly as before the
 * walkthrough arc landed — kept byte-for-byte so existing programs (incl.
 * connect-explainer's explainer-mode stat-drop and prospect branding)
 * render unchanged.
 */
function renderMarketing(
  spec: ProgramSpec,
  brand: { tagline: string; cycleSteps: readonly [string, string, string, string] },
  timeline: { totalFrames: number; beats: ResolvedBeat[] },
  cycleStepStartSeconds: VideoProps["cycleStepStartSeconds"],
) {
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
    <>
      <Sequence durationInFrames={byId.handoff.startFrame + byId.handoff.durationFrames}>
        <Intro
          programName={spec.name}
          brand={brand}
          beatFrames={introBeats}
          // Cycle highlight syncs to the keyword positions in this
          // beat's narration ("learn"/"deliver"/"verif"/"pay") so the
          // ring lights up the right step as the voiceover names it.
          // When cycleStepStartSeconds is provided (post-2026-05-19,
          // from ElevenLabs alignment), Cycle uses the exact spoken
          // timestamps; otherwise it falls back to a word-index
          // proportional estimate parsed from the narration text.
          cycleNarration={spec.narration?.by_beat?.cycle}
          cycleStepStartSeconds={cycleStepStartSeconds}
          prospectName={spec.prospect?.name}
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
      {spec.prospect && (
        <Sequence durationInFrames={timeline.totalFrames}>
          <ProspectBranding name={spec.prospect.name} logoSrc={spec.prospect.logo_asset} />
        </Sequence>
      )}
    </>
  );
}

/**
 * Walkthrough arc (connect-walkthrough template). Rendered generically
 * from the spec's beats: an intro_title card, N body_walkthrough sections
 * (ProgramBody plays each clip range full-bleed with its lower-third), and
 * an outro_card (the brand Outro). No hard-pull of fixed beat ids — any
 * beats list shaped this way renders. The per-beat CaptionBar + VO ride on
 * top via the shared ProgramVideo path.
 */
function renderWalkthrough(spec: ProgramSpec, beats: ResolvedBeat[]) {
  const titleBeat = beats.find((b) => b.kind === "intro_title");
  const bodyBeats = beats.filter((b) => b.kind === "body_walkthrough");
  const outroBeat = beats.find((b) => b.kind === "outro_card");
  return (
    <>
      {titleBeat && (
        <Sequence from={titleBeat.startFrame} durationInFrames={titleBeat.durationFrames}>
          <TitleCard title={spec.name} subtitle={spec.tagline} />
        </Sequence>
      )}
      {bodyBeats.length > 0 && (
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
      )}
      {outroBeat && (
        <Sequence from={outroBeat.startFrame} durationInFrames={outroBeat.durationFrames}>
          <Outro programUrl={spec.program_url} />
        </Sequence>
      )}
    </>
  );
}

export const RemotionRoot: React.FC = () => {
  const defaultSlug = "mbw";
  const spec = applyManifestRefs(parseProgramSpec(PROGRAMS_REGISTRY[defaultSlug]));
  const timeline = resolveBeats(
    effectiveBeatsForSpec(defaults, spec),
    spec.beat_overrides ?? {},
  );
  return (
    <Composition
      id="ProgramVideo"
      component={ProgramVideo as unknown as React.FC<Record<string, unknown>>}
      durationInFrames={timeline.totalFrames}
      fps={timeline.fps}
      width={1920}
      height={1080}
      defaultProps={{ programSlug: defaultSlug, captions: [] }}
      // Duration must reflect the spec actually being rendered, not the
      // bundled mbw default. Explainer-mode specs drop the problem/impact
      // beats (filterDefaultsForSpec), so their timeline is ~18s shorter
      // than mbw's; without recomputing here the composition keeps mbw's
      // length and an explainer render gets a black tail past its content.
      calculateMetadata={({ props }) => {
        const p = props as unknown as VideoProps;
        const yamlText = p.specYaml ?? PROGRAMS_REGISTRY[p.programSlug];
        if (!yamlText) return { durationInFrames: timeline.totalFrames, fps: timeline.fps };
        const s = applyManifestRefs(parseProgramSpec(yamlText));
        const merged = { ...(s.beat_overrides ?? {}), ...(p.beatOverrides ?? {}) };
        const tl = resolveBeats(effectiveBeatsForSpec(defaults, s), merged);
        return { durationInFrames: tl.totalFrames, fps: tl.fps };
      }}
    />
  );
};

registerRoot(RemotionRoot);
