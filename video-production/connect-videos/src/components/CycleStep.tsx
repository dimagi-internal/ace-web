import { Gif } from "@remotion/gif";
import { spring, staticFile, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { theme } from "../theme";

interface Props {
  label: "Learn" | "Deliver" | "Verify" | "Pay";
  index: number;
  // True while this step is the one being narrated.
  active?: boolean;
}

// Each cycle step has a matching animated gif fetched from
// connect.dimagi.com's prelogin marketing surface (downloaded into
// public/cycle/). Using @remotion/gif means each frame of the gif is
// composited into the rendered mp4 (vs. <Img> which would freeze on
// frame 0). Falls back gracefully — if the gif fails to load (cache
// miss, broken file), Remotion renders nothing and the surrounding
// label/ring still indicate which step is highlighted.
const GIF_PATH: Record<Props["label"], string> = {
  Learn: "cycle/learn.gif",
  Deliver: "cycle/deliver.gif",
  Verify: "cycle/verify.gif",
  Pay: "cycle/pay.gif",
};

export const CycleStep: React.FC<Props> = ({ label, index, active = false }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  // Stagger entrance so the four steps appear in order at the top of the
  // cycle beat.
  const enter = spring({ frame: frame - index * 6, fps, config: { damping: 14 } });
  // Smoothly cross-fade focus when active changes (avoids a hard jump).
  const focus = spring({
    frame: frame - index * 4,
    fps,
    config: { damping: 18, stiffness: 80 },
    from: active ? 0 : 1,
    to: active ? 1 : 0,
  });
  const scale = interpolate(focus, [0, 1], [0.88, 1.06]);
  const dim = interpolate(focus, [0, 1], [0.35, 1]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
        opacity: enter * dim,
        transform: `translateY(${(1 - enter) * 20}px) scale(${scale})`,
        transition: "none",
        fontFamily: theme.fonts.sans,
        color: theme.colors.foreground,
      }}
    >
      <div
        style={{
          width: 220,
          height: 220,
          borderRadius: 9999,
          // Accent-colored ring around the gif. Becomes deeper + larger
          // shadow when the step is the one being narrated.
          background: active ? theme.colors.accentDeep : theme.colors.accent,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
          padding: 8,
          boxShadow: active
            ? "0 12px 36px rgba(40, 50, 160, 0.45)"
            : "0 4px 12px rgba(40, 50, 160, 0.18)",
        }}
      >
        <Gif
          src={staticFile(GIF_PATH[label])}
          width={204}
          height={204}
          fit="cover"
          loopBehavior="loop"
          style={{ borderRadius: 9999 }}
        />
      </div>
      <div
        style={{
          fontSize: 38,
          fontWeight: active ? 800 : 500,
          color: active ? theme.colors.foreground : theme.colors.muted,
        }}
      >
        {label}
      </div>
    </div>
  );
};
