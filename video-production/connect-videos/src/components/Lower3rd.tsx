import { theme } from "../theme";

export const Lower3rd: React.FC<{ text: string }> = ({ text }) => (
  <div
    style={{
      position: "absolute",
      left: 64,
      bottom: 96,
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
