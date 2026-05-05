interface Props {
  title: string;
  children: React.ReactNode;
}

export function SummarySection({ title, children }: Props) {
  return (
    <section>
      <h2 className="mb-4 text-sm uppercase tracking-[0.18em] text-muted-foreground">
        {title}
      </h2>
      <div>{children}</div>
    </section>
  );
}
