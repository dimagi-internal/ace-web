import { Img, useCurrentFrame, interpolate } from "remotion";

interface Props {
  src: string;
  durationFrames: number;
  zoomFrom?: number;
  zoomTo?: number;
}

export const KenBurns: React.FC<Props> = ({
  src,
  durationFrames,
  zoomFrom = 1.0,
  zoomTo = 1.08,
}) => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, durationFrames], [zoomFrom, zoomTo], {
    extrapolateRight: "clamp",
  });
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <Img
        src={src}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${scale})`,
          transformOrigin: "center",
        }}
      />
    </div>
  );
};
