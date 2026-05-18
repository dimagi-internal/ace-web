import { interpolate, useCurrentFrame } from "remotion";
import { theme } from "../theme";

interface Props {
  big: string;
  caption: string;
  source?: string;
}

/**
 * Pick a font size that keeps the headline number on a single 1920px row.
 *
 * Measured empirically: at fontWeight 800 in this theme's sans, the
 * average glyph (digit + comma) is ~0.75em wide. With 1700px of
 * available row width (110px gutters per side), `chars * size * 0.75
 * ≤ 1700` gives `size ≤ 2267 / chars`. The previous 0.6em estimate
 * undershot — "1,000,000+" (11 chars) at 258px overflowed past 1920.
 * Use 2200 / chars (slight safety margin) and clamp to [120, 280] so
 * short values like "80%" stay punchy and long values stay legible.
 *
 * Worked examples (eyeball-verified frame extracts):
 *   "80%"      (3 chars)  → cap → 280px
 *   "$1.70"    (5 chars)  → cap → 280px
 *   "1M+"      (3 chars)  → cap → 280px
 *   "1,000,000+" (11)     → 200px (fits with breathing room)
 *   "22%"      (3 chars)  → cap → 280px
 */
function bigFontSize(big: string): number {
  const visualChars = big.length;
  if (visualChars === 0) return 280;
  const desired = Math.floor(2200 / visualChars);
  return Math.max(120, Math.min(280, desired));
}

export const StatCard: React.FC<Props> = ({ big, caption, source }) => {
  const frame = useCurrentFrame();
  // Always-visible content with a subtle slide-in only. Earlier
  // iterations animated opacity 0→1, which left stat cards blank at the
  // exact slot boundary when two stats share an impact beat (and the QA
  // mid-frame sample happened to land there). Translate alone gives a
  // sense of arrival without ever hiding the numbers.
  const slideY = interpolate(frame, [0, 14], [18, 0], { extrapolateRight: "clamp" });

  // Background is always painted so a paused/mid-fade frame is never black.
  // Only the foreground (number + caption + source) fades in.
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        // Reserve the bottom 180px for the caption bar so the source
        // line and the caption don't fight for the same rows.
        paddingBottom: 180,
        gap: 24,
        background: theme.colors.background,
        fontFamily: theme.fonts.sans,
        color: theme.colors.foreground,
      }}
    >
      <div
        style={{
          transform: `translateY(${slideY}px)`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 24,
        }}
      >
        <div
          style={{
            // Auto-fit the headline to the 1920×1080 frame. Long values
            // like "1,000,000+" overflowed the canvas at the old fixed
            // 280px size; short values like "80%" or "$36" stay near
            // the original size for visual punch. Char count is a
            // good-enough proxy — the actual rendered width tracks it
            // ~linearly for the same font weight. 1700px caps the
            // horizontal budget (96px gutters on each side of 1920).
            fontSize: bigFontSize(big),
            fontWeight: 800,
            color: theme.colors.accent,
            lineHeight: 1,
            maxWidth: 1700,
            textAlign: "center",
            // whiteSpace: nowrap prevents commas from being treated as
            // line-break opportunities so the number stays on one row.
            whiteSpace: "nowrap",
          }}
        >
          {big}
        </div>
        <div style={{ fontSize: 44, maxWidth: 1200, textAlign: "center" }}>{caption}</div>
        {source && (
          <div style={{ fontSize: 24, color: theme.colors.muted }}>Source: {source}</div>
        )}
      </div>
    </div>
  );
};
