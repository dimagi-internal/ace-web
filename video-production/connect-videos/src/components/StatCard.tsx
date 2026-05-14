import { interpolate, useCurrentFrame } from "remotion";
import { theme } from "../theme";

interface Props {
  big: string;
  caption: string;
  source?: string;
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
        <div style={{ fontSize: 280, fontWeight: 800, color: theme.colors.accent, lineHeight: 1 }}>
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
