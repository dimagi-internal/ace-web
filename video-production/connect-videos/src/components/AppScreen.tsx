import { Video, Img, staticFile, useVideoConfig } from "remotion";
import { theme } from "../theme";

interface Props {
  asset: string;
  // Per-beat caption was a third text channel competing with the
  // narration caption bar. Kept as an optional escape hatch but
  // suppressed by default so we don't double-up text on screen.
  caption?: string;
  showCaption?: boolean;
  // Where in the source clip to begin playback (when asset is a video).
  // Mirrors clip-level start_seconds for scene clips so per-clip range
  // editing works the same way for product beats.
  startSeconds?: number;
}

const isVideo = (s: string) => /\.(mp4|webm|mov)$/i.test(s);

export const AppScreen: React.FC<Props> = ({ asset, caption, showCaption = false, startSeconds = 0 }) => {
  const { fps } = useVideoConfig();
  const src = asset.startsWith("http") ? asset : staticFile(asset);
  const startFrom = Math.round(startSeconds * fps);
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: theme.colors.background,
        fontFamily: theme.fonts.sans,
      }}
    >
      <div
        style={{
          width: 540,
          height: 960,
          borderRadius: 56,
          background: "#000",
          padding: 16,
          boxShadow: "0 24px 64px rgba(0,0,0,0.25)",
        }}
      >
        <div style={{ width: "100%", height: "100%", borderRadius: 40, overflow: "hidden" }}>
          {isVideo(asset) ? (
            <Video
              src={src}
              startFrom={startFrom}
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
              onError={() => {
                /* Missing asset — render blank frame; drop real file into assets/ to fix */
              }}
            />
          ) : (
            <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          )}
        </div>
      </div>
      {caption && showCaption && (
        <div
          style={{
            position: "absolute",
            right: 96,
            top: "50%",
            transform: "translateY(-50%)",
            maxWidth: 560,
            color: theme.colors.foreground,
            fontSize: 42,
            fontWeight: 600,
          }}
        >
          {caption}
        </div>
      )}
    </div>
  );
};
