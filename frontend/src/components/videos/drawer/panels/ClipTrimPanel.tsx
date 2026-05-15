interface Props {
  clipKind: "scene-clip" | "product-beat";
  index: number;
  onCommit: () => void;
  onCancel: () => void;
}

export function ClipTrimPanel(_props: Props) {
  return <div data-testid="cliptrim-stub" />;
}
