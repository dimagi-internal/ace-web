import { AbsoluteFill, Sequence, useVideoConfig, spring, useCurrentFrame } from "remotion";
import { theme } from "../theme";
import { CycleStep } from "../components/CycleStep";
import { Logo } from "../components/Logo";

interface Brand {
  tagline: string;
  cycleSteps: readonly [string, string, string, string];
}

interface Props {
  programName: string;
  brand: Brand;
  beatFrames: { hook: number; cycle: number; handoff: number };
}

const Hook: React.FC<{ tagline: string }> = ({ tagline }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 14 } });
  return (
    <AbsoluteFill
      style={{
        background: theme.colors.background,
        alignItems: "center",
        justifyContent: "center",
        fontFamily: theme.fonts.display,
        color: theme.colors.foreground,
        padding: 96,
        gap: 56,
        textAlign: "center",
        opacity: enter,
      }}
    >
      <Logo height={96} variant="dark" />
      <div
        style={{
          fontSize: 80,
          fontWeight: 700,
          lineHeight: 1.1,
          maxWidth: 1500,
          background: theme.gradients.text,
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
          color: "transparent",
        }}
      >
        {tagline}
      </div>
    </AbsoluteFill>
  );
};

const Cycle: React.FC<{ durationFrames: number; steps: readonly [string, string, string, string] }> = ({ durationFrames, steps }) => {
  const frame = useCurrentFrame();
  // Reserve the first 12 frames (0.4s @ 30fps) for all four steps to
  // appear staggered, then walk the highlight across the remaining time.
  const stepDuration = (durationFrames - 12) / 4;
  const activeIndex = Math.min(3, Math.max(0, Math.floor((frame - 12) / stepDuration)));
  return (
    <AbsoluteFill
      style={{
        background: theme.colors.background,
        alignItems: "center",
        justifyContent: "center",
        gap: 80,
        flexDirection: "row",
      }}
    >
      {steps.map((label, i) => (
        <CycleStep key={label} label={label} index={i} active={i === activeIndex} />
      ))}
    </AbsoluteFill>
  );
};

const Handoff: React.FC<{ programName: string }> = ({ programName }) => (
  <AbsoluteFill
    style={{
      background: theme.colors.background,
      alignItems: "center",
      justifyContent: "center",
      fontFamily: theme.fonts.display,
      color: theme.colors.foreground,
      padding: 96,
      textAlign: "center",
    }}
  >
    <div style={{ fontSize: 64, fontWeight: 500, lineHeight: 1.2 }}>
      Here's how it works for
      <br />
      <span style={{ color: theme.colors.accent, fontWeight: 700 }}>{programName}</span>.
    </div>
  </AbsoluteFill>
);

export const Intro: React.FC<Props> = ({ programName, brand, beatFrames }) => (
  <>
    <Sequence durationInFrames={beatFrames.hook}>
      <Hook tagline={brand.tagline} />
    </Sequence>
    <Sequence from={beatFrames.hook} durationInFrames={beatFrames.cycle}>
      <Cycle durationFrames={beatFrames.cycle} steps={brand.cycleSteps} />
    </Sequence>
    <Sequence from={beatFrames.hook + beatFrames.cycle} durationInFrames={beatFrames.handoff}>
      <Handoff programName={programName} />
    </Sequence>
  </>
);
