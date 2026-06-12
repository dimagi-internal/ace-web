import { interpolate, useCurrentFrame } from "remotion";
import { theme } from "../theme";

interface Props {
  text: string;
}

/**
 * Vertical pixels reserved at the bottom of the frame for the
 * narration caption. Other on-screen text (lower-thirds, stat-card
 * captions, etc) MUST start above frame.height - CAPTION_RESERVED_BOTTOM
 * to avoid collision with the caption. Single source of truth — every
 * other component that pins to the bottom references this constant.
 *
 * Sized for a 2-line caption pill at fontSize 34 / lineHeight 1.3 plus
 * the pill padding and a small floor margin. Bumping the caption font
 * size or line count means bumping this constant.
 */
export const CAPTION_RESERVED_BOTTOM = 168;

/**
 * Narration caption — a centered "scrim pill" rather than outlined text.
 *
 * A semi-transparent dark lozenge hugs the verbatim narration line, so it
 * stays equally legible on a light card, a dark/blue motion-graphic card,
 * or busy field b-roll — without the chunky outlined-sticker look the old
 * 800-weight + 2px text-stroke treatment had. The pill reads as a
 * deliberate, broadcast-style subtitle layer instead of text floating on
 * whatever is behind it. Inter 600 (not 800) keeps it refined; the pill
 * shrinks to fit short lines and wraps long ones at maxWidth.
 *
 * Each caption renders inside its own Remotion <Sequence>, so
 * useCurrentFrame resets to 0 at the caption's start — we use that for a
 * quick fade + rise in.
 */
export const CaptionBar: React.FC<Props> = ({ text }) => {
  const frame = useCurrentFrame();
  if (!text) return null;

  const enter = interpolate(frame, [0, 6], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const rise = (1 - enter) * 10;

  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 52,
        display: "flex",
        justifyContent: "center",
        padding: "0 120px",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          opacity: enter,
          transform: `translateY(${rise}px)`,
          maxWidth: 1040,
          background: "rgba(10, 6, 32, 0.66)",
          borderRadius: 16,
          padding: "12px 28px",
          textAlign: "center",
          fontFamily: theme.fonts.caption,
          color: theme.colors.captionFg,
          fontSize: 34,
          fontWeight: 600,
          letterSpacing: "-0.005em",
          lineHeight: 1.3,
          // Soft shadow lifts the pill off the background; a faint text
          // shadow keeps the glyphs crisp over the translucent fill.
          boxShadow: "0 6px 22px rgba(10, 6, 32, 0.30)",
          textShadow: "0 1px 2px rgba(0, 0, 0, 0.35)",
        }}
      >
        {text}
      </div>
    </div>
  );
};
