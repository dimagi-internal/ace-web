import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { CAPTION_RESERVED_BOTTOM } from "./CaptionBar";

interface Props {
  headline: string;
  components: string[];
  subhead?: string;
}

/**
 * The "how the program is built" card — the program-designer AI cut's
 * body_ai_build beat. A pure motion graphic (no library clip): the
 * headline holds, then the program's Connect components assemble in as
 * staggered chips, then the optional sub-headline arrives.
 *
 * Background is always painted (never a black frame on a paused/QA
 * mid-frame). Content sits above CAPTION_RESERVED_BOTTOM so the narration
 * caption underneath never collides — same discipline as StatCard.
 */
export const AiBuildCard: React.FC<Props> = ({ headline, components, subhead }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Headline slides up and settles immediately.
  const headlineY = interpolate(frame, [0, 16], [24, 0], { extrapolateRight: "clamp" });

  return (
    <div
      style={{
        // Background fills the WHOLE frame (incl. behind the caption pill)
        // so the narration caption never sits on a mismatched dark strip
        // below the card. Content is confined separately, below.
        position: "absolute",
        inset: 0,
        background: theme.gradients.primary,
        fontFamily: theme.fonts.sans,
        color: "#FFFFFF",
        textAlign: "center",
      }}
    >
    <div
      style={{
        position: "absolute",
        // Confine all content to the band above the caption zone and
        // center within it, so neither a tall (multi-line) headline nor
        // the subhead can clip off the top or collide with the narration
        // caption underneath. Height = frame - caption-reserved band.
        top: 0,
        left: 0,
        right: 0,
        bottom: CAPTION_RESERVED_BOTTOM + 24,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        paddingLeft: theme.spacing.xl,
        paddingRight: theme.spacing.xl,
        // Clear the top-left ProspectBranding badge (≈110px tall) on
        // branded cuts so a multi-line headline never tucks under it.
        paddingTop: 108,
        // Tighter stack so a dense card (2-line headline + 4 chips +
        // subhead) clears a 3-line caption pill below without the subhead
        // tucking under it.
        gap: 28,
      }}
    >
      <div
        style={{
          transform: `translateY(${headlineY}px)`,
          fontSize: 52,
          fontWeight: 800,
          lineHeight: 1.12,
          maxWidth: 1640,
          letterSpacing: "-0.01em",
        }}
      >
        {headline}
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: 20,
          maxWidth: 1640,
        }}
      >
        {components.map((c, i) => {
          // Stagger each chip ~7 frames apart, springing in after the
          // headline has settled (~12 frames).
          const appear = spring({
            frame: frame - 12 - i * 7,
            fps,
            config: { damping: 200, mass: 0.6 },
          });
          return (
            <div
              key={i}
              style={{
                opacity: appear,
                transform: `translateY(${(1 - appear) * 16}px) scale(${0.92 + appear * 0.08})`,
                padding: "16px 30px",
                background: "rgba(255,255,255,0.12)",
                border: "1px solid rgba(255,255,255,0.35)",
                borderRadius: theme.radii.lg,
                fontSize: 38,
                fontWeight: 600,
                backdropFilter: "blur(2px)",
                whiteSpace: "nowrap",
              }}
            >
              {c}
            </div>
          );
        })}
      </div>

      {subhead && (
        <div
          style={{
            opacity: interpolate(
              frame,
              [12 + components.length * 7, 12 + components.length * 7 + 14],
              [0, 1],
              { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
            ),
            fontSize: 32,
            fontWeight: 400,
            maxWidth: 1400,
            color: "rgba(255,255,255,0.92)",
          }}
        >
          {subhead}
        </div>
      )}
    </div>
    </div>
  );
};
