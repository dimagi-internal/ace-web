import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { Logo } from "../components/Logo";

interface Props {
  programUrl: string;
}

export const Outro: React.FC<Props> = ({ programUrl }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 14 } });
  return (
    <AbsoluteFill
      style={{
        background: theme.gradients.primary,
        color: "white",
        alignItems: "center",
        justifyContent: "center",
        gap: 36,
        fontFamily: theme.fonts.display,
        padding: 96,
        textAlign: "center",
        opacity: enter,
      }}
    >
      <Logo height={112} variant="light" />
      <div
        style={{
          fontSize: 48,
          fontWeight: 500,
          background: theme.gradients.textOnDark,
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
          color: "transparent",
        }}
      >
        Powering the Frontline. Paying for Results.
      </div>
      <div style={{ fontSize: 28, color: theme.colors.sky, marginTop: 16 }}>
        Become a delivery partner — {programUrl.replace(/^https?:\/\//, "")}
      </div>
    </AbsoluteFill>
  );
};
