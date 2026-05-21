import { spring, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { theme } from "../theme";

interface Props {
  label: "Learn" | "Deliver" | "Verify" | "Pay";
  index: number;
  // True while this step is the one being narrated.
  active?: boolean;
}

// Each cycle step has a brand color and a matching glyph, lifted from
// the "click a step" graphic on connect.dimagi.com's prelogin homepage.
// Two visual states per step:
//
//   active  = filled circle in BRAND[label], glyph stroked in white
//   passive = white-fill circle outlined in BRAND[label], glyph stroked
//             in BRAND[label]
//
// SVG path data is inlined (not loaded from public/) so the renderer
// has zero asset-loading risk for this template element. Bake-once,
// render-everywhere.
const BRAND: Record<Props["label"], string> = {
  Learn: "#16006D",
  Deliver: "#5D70D2",
  Verify: "#FC5F36",
  Pay: "#1B998B",
};

// Inline icon glyphs centered on (0,0), drawn with stroke=currentColor.
// Sized to fit comfortably inside a 144px-diameter circle.
const Glyph: React.FC<{ label: Props["label"] }> = ({ label }) => {
  const stroke = { stroke: "currentColor", fill: "none", strokeLinecap: "round", strokeLinejoin: "round" } as const;
  switch (label) {
    case "Learn":
      // A laptop/screen with three text-lines and two stand legs —
      // mirrors the homepage "Learn" glyph.
      return (
        <g {...stroke} strokeWidth={2.4}>
          <rect x={-26} y={-16} width={52} height={26} rx={2.5} />
          <line x1={-18} y1={-9} x2={2} y2={-9} />
          <line x1={-18} y1={-2} x2={16} y2={-2} />
          <line x1={-18} y1={6} x2={-2} y2={6} />
          <line x1={-14} y1={11} x2={-14} y2={17} />
          <line x1={14} y1={11} x2={14} y2={17} />
        </g>
      );
    case "Deliver":
      // Heart with a small + (cross) inside — the "care" mark.
      return (
        <g {...stroke} strokeWidth={2.4}>
          <path d="M0 17 C -19 0, -19 -17, -9 -17 C -5 -17, 0 -12, 0 -7 C 0 -12, 5 -17, 9 -17 C 19 -17, 19 0, 0 17 Z" />
          <line x1={-5} y1={-4} x2={5} y2={-4} strokeWidth={2.8} />
          <line x1={0} y1={-9} x2={0} y2={1} strokeWidth={2.8} />
        </g>
      );
    case "Verify":
      // Shield with checkmark — the verification mark.
      return (
        <g {...stroke} strokeWidth={2.4}>
          <path d="M0 -26 L-24 -17 L-24 5 L0 26 L24 5 L24 -17 Z" />
          <path d="M-11 -1 L-3 7 L11 -9" strokeWidth={3} />
        </g>
      );
    case "Pay":
      // Dollar sign rendered as line-art paths (vertical stroke + S-curve)
      // to match the line-weight + stroke vocabulary of Learn/Deliver/Verify.
      // Was previously an SVG <text>$</text> — under the cycle entrance
      // animation (the `enter` spring at damping:14 overshoots before
      // settling), the text element wobbled noticeably while the parent's
      // transform was changing: font hinting snaps each glyph to the pixel
      // grid at every scale increment, so the dollar sign appeared to
      // "shake" while the three vector-path glyphs scaled cleanly.
      // Switching to paths makes Pay scale geometrically like the rest.
      return (
        <g {...stroke} strokeWidth={3}>
          {/* Vertical stroke through the center */}
          <line x1={0} y1={-26} x2={0} y2={26} />
          {/* S-curve: upper half curves left, lower half curves right —
              mirrors the typographic dollar sign without the font path. */}
          <path d="M 13 -14 C 13 -22, 4 -22, -4 -22 C -12 -22, -13 -16, -13 -10 C -13 -4, -8 0, 0 0 C 8 0, 13 4, 13 10 C 13 16, 12 22, 4 22 C -4 22, -13 22, -13 14" />
        </g>
      );
  }
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
  const dim = interpolate(focus, [0, 1], [0.55, 1]);

  const brand = BRAND[label];

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 14,
        opacity: enter * dim,
        transform: `translateY(${(1 - enter) * 20}px) scale(${scale})`,
        transition: "none",
        fontFamily: theme.fonts.sans,
        color: theme.colors.foreground,
      }}
    >
      <svg
        width={176}
        height={176}
        viewBox="-88 -88 176 176"
        // Glyph inherits currentColor — white when active, brand when
        // passive. The matching circle below uses brand for the
        // stroke/fill so the whole step reads as one color family.
        style={{
          color: active ? "#FFFFFF" : brand,
          filter: active
            ? `drop-shadow(0 14px 30px ${brand}55)`
            : `drop-shadow(0 4px 10px ${brand}22)`,
        }}
      >
        <circle
          cx={0}
          cy={0}
          r={70}
          fill={active ? brand : "#FFFFFF"}
          stroke={brand}
          strokeWidth={active ? 0 : 3}
        />
        <Glyph label={label} />
      </svg>
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
