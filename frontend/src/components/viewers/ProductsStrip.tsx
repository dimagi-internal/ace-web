import type { RunProduct } from "@/api/types.ws";
import { Glossed } from "@/components/glossary/Glossed";
import { cn } from "@/lib/utils";

import { kindMeta } from "./productKinds";
import { useViewer } from "./ViewerContext";

interface Props {
  products: readonly RunProduct[];
  /** Replay: has the cursor reached the beat that made this? Omitted = all built. */
  isRevealed?: (product: RunProduct) => boolean;
  /** Replay: products that appeared on the current beat, for a brief highlight. */
  justRevealed?: ReadonlySet<string>;
}

/**
 * "What this run built" — one chip per product, click to open it.
 *
 * The PDD, the apps, the Connect opportunity and the training deck used to
 * be filenames inside an expanded skill row; this puts them at the top of
 * the screen. In a replay, a product the cursor hasn't reached yet is a
 * dashed placeholder showing only its KIND ("CommCare app") — its real name
 * is content the run hadn't produced yet, so it isn't shown until it has.
 */
export function ProductsStrip({ products, isRevealed, justRevealed }: Props) {
  const viewer = useViewer();
  if (products.length === 0) return null;
  const built = products.filter((p) => !isRevealed || isRevealed(p)).length;

  return (
    <section aria-label="What this run built" className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {isRevealed ? `Built so far · ${built}/${products.length}` : "What this run built"}
      </span>
      {products.map((p) => {
        const meta = kindMeta(p.kind);
        const revealed = !isRevealed || isRevealed(p);
        const fresh = justRevealed?.has(p.id) ?? false;
        return (
          <button
            key={p.id}
            type="button"
            disabled={!revealed}
            onClick={() => viewer?.open({ type: "product", product: p })}
            title={
              revealed
                ? `${meta.label} — click to open`
                : `${meta.label} — not built yet at this point in the run`
            }
            className={cn(
              "inline-flex max-w-[260px] items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-all duration-500",
              revealed
                ? "border-border bg-card text-foreground hover:border-primary/60 hover:bg-primary/5"
                : "cursor-default border-dashed border-border/70 bg-transparent text-muted-foreground/60",
              fresh && "border-primary bg-primary/10 ring-2 ring-primary/40",
            )}
          >
            <meta.icon className={cn("h-3.5 w-3.5 shrink-0", revealed && "text-primary")} aria-hidden />
            <span className="truncate">
              {revealed ? <Glossed text={p.title} /> : meta.label}
            </span>
          </button>
        );
      })}
    </section>
  );
}
