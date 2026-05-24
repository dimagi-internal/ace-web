interface Props {
  viewers: { email: string; name: string }[];
}

export function PresenceStrip({ viewers }: Props) {
  if (viewers.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 border-b border-border bg-muted/30 px-4 py-1.5 text-xs text-muted-foreground">
      <span className="mr-1">Viewing:</span>
      {viewers.map((v) => (
        <span
          key={v.email}
          className="inline-flex h-5 items-center rounded-full bg-muted px-2 text-xs font-medium"
          title={v.email}
        >
          {v.name || v.email.split("@")[0]}
        </span>
      ))}
    </div>
  );
}
