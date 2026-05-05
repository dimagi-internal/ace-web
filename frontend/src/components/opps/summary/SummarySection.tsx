interface Props {
  title: string;
  children: React.ReactNode;
}

/**
 * A titled section. The title sits above the rows in small uppercase
 * tracked-out type — quiet enough that the row content carries the
 * page, present enough to anchor each block.
 */
export function SummarySection({ title, children }: Props) {
  return (
    <section>
      <h2 className="mb-3 pb-3 border-b border-border text-[11px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
        {title}
      </h2>
      <div>{children}</div>
    </section>
  );
}
