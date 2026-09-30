import type { RunProduct } from "@/api/types.ws";
import { Glossed } from "@/components/glossary/Glossed";
import { cn } from "@/lib/utils";

import { ProductPreviews } from "./ProductPreviews";
import { kindMeta } from "./productKinds";
import { useViewer } from "./ViewerContext";

/** Kinds whose Drive file the viewer draws in the page. */
const FILE_KINDS: ReadonlySet<string> = new Set(["document", "deck", "sheet"]);

interface Props {
  product: RunProduct;
  /** Replay: the cursor hasn't reached the beat that made it. */
  unbuilt?: boolean;
  /** Replay: it appeared (or gained screenshots) on this very beat. */
  fresh?: boolean;
}

/**
 * One thing a run built, as the rail shows it: what kind of thing, its name,
 * and — when ACE photographed it — a row of screenshots. Click opens it.
 *
 * Not built yet (replay) it is just its kind, dashed: its real name is
 * content the run hadn't produced yet.
 */
export function ProductCard({ product, unbuilt = false, fresh = false }: Props) {
  const viewer = useViewer();
  const meta = kindMeta(product.kind);

  if (unbuilt) {
    return (
      <div
        role="img"
        aria-label={`${meta.label} — not built yet`}
        title={`${meta.label} — not built yet at this point in the run`}
        className="flex items-center gap-2 rounded-md border border-dashed border-border/70 px-2 py-1.5 text-[11px] text-muted-foreground/60"
      >
        <meta.icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
        {meta.label}
      </div>
    );
  }

  const previews = product.previews ?? [];
  // The rule (output-previews spec, addendum): every output is a file the page
  // shows, or has screenshots. Say so quietly when one is neither, rather than
  // leaving a reader to wonder whether the pictures failed to load.
  const shownAsFile = !!product.file_id && FILE_KINDS.has(product.kind);
  const unpictured = !shownAsFile && previews.length === 0;
  return (
    <div
      className={cn(
        "rounded-md border bg-card transition-all duration-500",
        fresh ? "border-primary bg-primary/5 ring-2 ring-primary/40" : "border-border/70",
      )}
    >
      <button
        type="button"
        onClick={() => viewer?.open({ type: "product", product })}
        title={`${meta.label} — click to open`}
        className="flex w-full items-start gap-2 px-2 py-1.5 text-left hover:bg-accent/40"
      >
        <meta.icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-xs font-medium text-foreground">
            <Glossed text={product.title} />
          </span>
          <span className="block truncate text-[10px] text-muted-foreground">
            {meta.label}
            {unpictured && <span className="text-muted-foreground/60"> · no screenshot yet</span>}
          </span>
        </span>
      </button>
      {previews.length > 0 && (
        <div className="px-2 pb-2">
          <ProductPreviews previews={previews} of={product.title} compact />
        </div>
      )}
    </div>
  );
}
