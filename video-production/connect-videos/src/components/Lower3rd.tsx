import { theme } from "../theme";
import { CAPTION_RESERVED_BOTTOM } from "./CaptionBar";

/**
 * Lower-third country/program label. Positioned above the caption-reserved
 * zone so it never collides with the narration caption underneath. See
 * CAPTION_RESERVED_BOTTOM in CaptionBar.tsx — that constant is the
 * single source of truth for the bottom zone the caption owns.
 */
export const Lower3rd: React.FC<{ text: string }> = ({ text }) => (
  <div
    style={{
      position: "absolute",
      left: 64,
      bottom: CAPTION_RESERVED_BOTTOM + 16,
      padding: "12px 24px",
      background: theme.colors.accent,
      color: "white",
      fontFamily: theme.fonts.sans,
      fontSize: 36,
      fontWeight: 600,
      borderRadius: theme.radii.sm,
    }}
  >
    {text}
  </div>
);
