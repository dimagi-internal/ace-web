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
  // Optional narration text for the cycle beat. Used only when
  // cycleStepStartSeconds isn't provided — falls back to the
  // word-index proportional estimate.
  cycleNarration?: string;
  // Exact seconds-into-cycle-audio at which each spoken keyword
  // starts. Extracted from ElevenLabs' alignment data at render time
  // (see voiceover.ts::wordStartSeconds). When provided, the highlight
  // transitions on the spoken word — no estimation.
  cycleStepStartSeconds?: {
    learn?: number;
    deliver?: number;
    verify?: number;
    pay?: number;
  };
  // Optional prospect name for a branded partnership cut. When present,
  // the hook adds a "A partnership proposal for <name>" line so the open
  // frames the whole video as made-for-them. Absent = generic explainer.
  prospectName?: string;
}

const Hook: React.FC<{ tagline: string; prospectName?: string }> = ({ tagline, prospectName }) => {
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
        gap: 40,
        textAlign: "center",
        opacity: enter,
      }}
    >
      <Logo height={96} variant="dark" />
      {prospectName && (
        <div style={{ fontSize: 38, fontWeight: 500, color: theme.colors.muted }}>
          A partnership proposal for{" "}
          <span style={{ color: theme.colors.accent, fontWeight: 700 }}>{prospectName}</span>
        </div>
      )}
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
  stepStartSeconds?: {
    learn?: number;
    deliver?: number;
    verify?: number;
    pay?: number;
  };
}> = ({ durationFrames, steps, narration, stepStartSeconds }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Three timing strategies, in order of preference:
  //   1. Concrete second-offsets from ElevenLabs alignment data
  //      (stepStartSeconds). The highlight transitions on the spoken
  //      word — what the user wants.
  //   2. Word-index proportional positions parsed from the narration
  //      text (positions[]). Reasonable estimate when alignment isn't
  //      available (e.g. Studio preview, or programs that haven't
  //      re-rendered post-alignment-switch).
  //   3. Even quarters across the beat duration. Last-resort fallback
  //      when there's no narration text at all.
  let activeIndex = 0;

  if (stepStartSeconds && (
    stepStartSeconds.learn !== undefined ||
    stepStartSeconds.deliver !== undefined ||
    stepStartSeconds.verify !== undefined ||
    stepStartSeconds.pay !== undefined
  )) {
    // The cycle audio runs synchronously with the cycle beat (the mux
    // step places the per-beat clip at beat.startFrame). So
    // "seconds into cycle audio" == "seconds into this Sequence" ==
    // frame / fps.
    const t = frame / fps;
    if (stepStartSeconds.pay !== undefined && t >= stepStartSeconds.pay) {
      activeIndex = 3;
    } else if (stepStartSeconds.verify !== undefined && t >= stepStartSeconds.verify) {
      activeIndex = 2;
    } else if (stepStartSeconds.deliver !== undefined && t >= stepStartSeconds.deliver) {
      activeIndex = 1;
    } else if (stepStartSeconds.learn !== undefined && t >= stepStartSeconds.learn) {
      activeIndex = 0;
    }
  } else {
    // Reserve the first 12 frames for the stagger-in.
    const STAGGER = 12;
    const walkBudget = durationFrames - STAGGER;
    const positions = keywordPositions(narration);
    if (positions) {
      const t = (frame - STAGGER) / walkBudget;
      for (let i = 0; i < 4; i++) {
        if (t >= positions[i]) activeIndex = i;
      }
    } else {
      const stepDuration = walkBudget / 4;
      activeIndex = Math.floor((frame - STAGGER) / stepDuration);
    }
    activeIndex = Math.min(3, Math.max(0, activeIndex));
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

/**
 * Title card for the connect-ddd-walkthrough explainer arc (intro_title beat).
 * A simple logo + program name + subtitle with a spring fade — NO cycle
 * ring or stat cards (that machinery belongs to the marketing arc's
 * Intro/Cycle/Handoff). Exported so Root.tsx can render it directly for
 * the intro_title beat without pulling the full marketing Intro.
 */
export const TitleCard: React.FC<{ title: string; subtitle?: string }> = ({
  title,
  subtitle,
}) => {
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
        gap: 40,
        textAlign: "center",
        opacity: enter,
      }}
    >
      <Logo height={84} variant="dark" />
      <div
        style={{
          fontSize: 76,
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
        {title}
      </div>
      {subtitle && (
        <div style={{ fontSize: 34, fontWeight: 400, color: theme.colors.muted, maxWidth: 1300 }}>
          {subtitle}
        </div>
      )}
    </AbsoluteFill>
  );
};

export const Intro: React.FC<Props> = ({
  programName,
  brand,
  beatFrames,
  cycleNarration,
  cycleStepStartSeconds,
  prospectName,
}) => (
  <>
    <Sequence durationInFrames={beatFrames.hook}>
      <Hook tagline={brand.tagline} prospectName={prospectName} />
    </Sequence>
    <Sequence from={beatFrames.hook} durationInFrames={beatFrames.cycle}>
      <Cycle
        durationFrames={beatFrames.cycle}
        steps={brand.cycleSteps}
        narration={cycleNarration}
        stepStartSeconds={cycleStepStartSeconds}
      />
    </Sequence>
    <Sequence from={beatFrames.hook + beatFrames.cycle} durationInFrames={beatFrames.handoff}>
      <Handoff programName={programName} />
    </Sequence>
  </>
);
