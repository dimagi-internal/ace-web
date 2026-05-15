interface Props {
  path: string;
  onCommit: () => void;
  onCancel: () => void;
}

export function StatPanel(_props: Props) {
  return <div data-testid="stat-panel-stub" />;
}
