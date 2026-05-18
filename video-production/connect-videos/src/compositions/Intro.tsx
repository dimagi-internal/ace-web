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
  // Optional narration text for the cycle beat. When provided, the
  // cycle highlight walks at the timestamps where "learn", "deliver",
  // "verify(ied)" and "pay(ied/paid)" appear in the audio (estimated
  // proportional to word position). Without it, falls back to evenly
  // spaced quarters.
  cycleNarration?: string;
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

/**
 * Find the word index where the narration first mentions the cycle
 * verb for each step ("learn", "deliver", "verif" — matches verify /
 * verified, "pay" — matches pay / paid). Returns 4 normalized
 * positions [0..1] for the highlight transitions, or `null` if any
 * keyword is missing so the caller can fall back to even spacing.
 *
 * Why proportional-by-word-index instead of TTS-aligned timestamps?
 * The renderer doesn't emit per-word timing data (ElevenLabs doesn't
 * give us one without alignment models). Word count maps reasonably
 * linearly to time at typical reading speed, so a word-index proxy is
 * close enough to feel right without bringing in an alignment lib.
 */
function keywordPositions(narration: string | undefined): readonly [number, number, number, number] | null {
  if (!narration) return null;
  // Lowercase + split on whitespace; punctuation stays attached to
  // words but the substring check is forgiving.
  const words = narration.toLowerCase().trim().split(/\s+/);
  if (words.length < 4) return null;
  const findIndex = (stems: string[]): number => {
    for (let i = 0; i < words.length; i++) {
      if (stems.some((s) => words[i].includes(s))) return i;
    }
    return -1;
  };
  const learn = findIndex(["learn"]);
  const deliver = findIndex(["deliver"]);
  const verify = findIndex(["verif"]);
  // "pay" is a substring of common words (paymen, days, etc.); use
  // the more specific stems to avoid false hits.
  const pay = findIndex(["paid", " pay ", "pay."]);
  // Fallback for the "pay" case: scan from the END of the string for
  // a final "pay" / "paid", which is where the cycle narration always
  // closes.
  let payIdx = pay;
  if (payIdx === -1) {
    for (let i = words.length - 1; i >= 0; i--) {
      if (words[i].startsWith("paid") || words[i].startsWith("pay")) { payIdx = i; break; }
    }
  }
  if (learn < 0 || deliver < 0 || verify < 0 || payIdx < 0) return null;
  // Enforce monotonic order — if the narration mentions "pay" before
  // "learn" (weird phrasing), bail rather than show a backwards walk.
  if (!(learn <= deliver && deliver <= verify && verify <= payIdx)) return null;
  const n = words.length;
  return [learn / n, deliver / n, verify / n, payIdx / n] as const;
}

const Cycle: React.FC<{
  durationFrames: number;
  steps: readonly [string, string, string, string];
  narration?: string;
}> = ({ durationFrames, steps, narration }) => {
  const frame = useCurrentFrame();
  // Reserve the first 12 frames (0.4s @ 30fps) for the stagger-in.
  const STAGGER = 12;
  const walkBudget = durationFrames - STAGGER;
  const positions = keywordPositions(narration);
  let activeIndex: number;
  if (positions) {
    // The highlight switches to step i at positions[i] * walkBudget.
    // We pick the highest i whose boundary is already past.
    const t = (frame - STAGGER) / walkBudget; // 0..1
    activeIndex = 0;
    for (let i = 0; i < 4; i++) {
      if (t >= positions[i]) activeIndex = i;
    }
    activeIndex = Math.min(3, Math.max(0, activeIndex));
  } else {
    // Fallback: even quarters (legacy behaviour for programs that
    // don't provide a cycle narration string).
    const stepDuration = walkBudget / 4;
    activeIndex = Math.min(3, Math.max(0, Math.floor((frame - STAGGER) / stepDuration)));
  }
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
        <CycleStep key={label} label={label as "Learn" | "Deliver" | "Verify" | "Pay"} index={i} active={i === activeIndex} />
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

export const Intro: React.FC<Props> = ({ programName, brand, beatFrames, cycleNarration }) => (
  <>
    <Sequence durationInFrames={beatFrames.hook}>
      <Hook tagline={brand.tagline} />
    </Sequence>
    <Sequence from={beatFrames.hook} durationInFrames={beatFrames.cycle}>
      <Cycle durationFrames={beatFrames.cycle} steps={brand.cycleSteps} narration={cycleNarration} />
    </Sequence>
    <Sequence from={beatFrames.hook + beatFrames.cycle} durationInFrames={beatFrames.handoff}>
      <Handoff programName={programName} />
    </Sequence>
  </>
);
