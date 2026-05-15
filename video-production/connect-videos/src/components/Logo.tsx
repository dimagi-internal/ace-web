import { Img, staticFile } from "remotion";

interface Props {
  height?: number;
  color?: string;
  variant?: "light" | "dark";
}

// Connect logo lockup. The SVG uses fill="currentColor" so we tint by
// applying CSS `color` on the wrapping element.
export const Logo: React.FC<Props> = ({ height = 96, color, variant = "dark" }) => {
  const tint = color ?? (variant === "light" ? "#FFFFFF" : "#0A0620");
  return (
    <div style={{ color: tint, display: "inline-flex", lineHeight: 0 }}>
      <Img
        src={staticFile("assets/shared/brand/connect-logo.svg")}
        style={{
          height,
          width: "auto",
          filter: variant === "light" ? "brightness(0) invert(1)" : undefined,
        }}
      />
    </div>
  );
};
