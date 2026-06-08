import { Img, staticFile } from "remotion";
import { theme } from "../theme";

interface Props {
  name: string;
  /** Resolved logo path (under public/) or absolute URL. Optional —
   *  name-only branding when absent (e.g. a greenfield pitch with no
   *  sourced logo). */
  logoSrc?: string;
}

/**
 * Persistent co-brand badge for a partnership-pitch / branded cut.
 *
 * Brand-safety discipline (see partnership-video design spec §9): the
 * Dimagi/Connect chrome stays dominant everywhere else; this badge only
 * signals "this cut was prepared for <Prospect>". It does NOT restyle the
 * video in the prospect's brand or imply the prospect authored it.
 *
 * Rendered as a top-level overlay across the whole video (Root.tsx) when
 * spec.prospect is present. The dark translucent pill keeps the text
 * legible over both the light cards (hook, stats) and the dark/full-bleed
 * beats (field b-roll, ai_build card, outro).
 */
export const ProspectBranding: React.FC<Props> = ({ name, logoSrc }) => {
  const isUrl = !!logoSrc && /^https?:\/\//.test(logoSrc);
  const src = logoSrc ? (isUrl ? logoSrc : staticFile(logoSrc)) : undefined;
  return (
    <div
      style={{
        position: "absolute",
        top: 44,
        left: 56,
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "12px 20px",
        background: "rgba(10,6,32,0.62)",
        border: "1px solid rgba(255,255,255,0.18)",
        borderRadius: theme.radii.md,
        backdropFilter: "blur(4px)",
        fontFamily: theme.fonts.sans,
      }}
    >
      {src && (
        <Img
          src={src}
          style={{ height: 40, width: "auto", borderRadius: 4, objectFit: "contain" }}
        />
      )}
      <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.15 }}>
        <span
          style={{
            fontSize: 16,
            fontWeight: 600,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "rgba(255,255,255,0.62)",
          }}
        >
          Prepared for
        </span>
        <span style={{ fontSize: 30, fontWeight: 700, color: "#FFFFFF" }}>{name}</span>
      </div>
    </div>
  );
};
