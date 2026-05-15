interface Props {
  beatId: string;
  onCommit: () => void;
  onCancel: () => void;
}

export function NarrationPanel(_props: Props) {
  return <div data-testid="narration-panel-stub" />;
}
