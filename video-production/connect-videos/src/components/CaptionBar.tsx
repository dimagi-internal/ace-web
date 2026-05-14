import { theme } from "../theme";

interface Props {
  text: string;
}

/**
 * Modern caption — Inter 800, tight letter-spacing, white fill with a
 * thin black stroke (paint-order:stroke fill so the stroke sits behind
 * the letterforms rather than thickening them) and a soft drop shadow
 * for legibility on light/dark/moving backgrounds.
 *
 * This is the style used in most production marketing videos and
 * YouTube documentary captions — much less chunky than text-shadow
 * outline tricks.
 */
export const CaptionBar: React.FC<Props> = ({ text }) => {
  if (!text) return null;
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 56,
        padding: "0 120px",
        textAlign: "center",
        fontFamily: theme.fonts.caption,
        color: "#FFFFFF",
        fontSize: 36,
        fontWeight: 800,
        letterSpacing: "-0.01em",
        lineHeight: 1.22,
        // Paint-order puts the stroke behind the letterforms, so the
        // visible glyph edge stays crisp. -webkit-text-stroke is the
        // only cross-browser way to get a proper outline; the layered
        // text-shadow alternative looks pixelated at high zoom.
        WebkitTextStroke: "2px #0A0620",
        paintOrder: "stroke fill" as const,
        // Soft drop shadow underneath the whole block for extra
        // legibility on busy backgrounds (e.g. street-market b-roll).
        filter: "drop-shadow(0 2px 6px rgba(10, 6, 32, 0.55))",
      }}
    >
      {text}
    </div>
  );
};
