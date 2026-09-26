import { useCallback, useEffect, useState } from "react";
import { ChevronRight, Sparkles, X } from "lucide-react";

import type { ReplayProduct } from "@/api/replay";
import { ProductBody } from "@/components/viewers/ProductViewer";
import { useViewer, ViewerHeading } from "@/components/viewers/ViewerContext";
import { cn } from "@/lib/utils";

import type { Replay } from "./useReplay";

/** How long each product holds the screen while the replay plays. */
export const SPOTLIGHT_MS = 4500;

interface Props {
  products: readonly ReplayProduct[];
  replay: Replay;
  onClose: () => void;
}

/**
 * The replay's "look what it just made" moment.
 *
 * When the cursor lands on the beat that brought products into being, they
 * pop up over the screen, one at a time, in the same viewer the products
 * strip opens. The point is the audience SEES the PDD, the app, the deck
 * appear as the run makes them, instead of taking a filename on faith.
 *
 * Playing: each product holds for {@link SPOTLIGHT_MS} while playback waits,
 * then it closes and the replay carries on. Driving by hand: it stays until
 * → (next product, then the next beat), ← (previous beat) or Esc.
 *
 * Its keys are handled on the document in the CAPTURE phase so they win over
 * the replay bar's window-level shortcuts — Esc here closes the pop-up, it
 * doesn't leave the replay.
 */
export function Spotlight({ products, replay, onClose }: Props) {
  const viewer = useViewer();
  const [index, setIndex] = useState(0);
  // Counting down only when it opened during playback; any hand on the
  // controls turns the countdown off.
  const [autoplay, setAutoplay] = useState(replay.playing);
  const product = products[index];

  // Hold the beat for as long as we're up, whether or not Play is on.
  useEffect(() => {
    replay.hold(true);
    return () => replay.hold(false);
  }, [replay]);

  const advance = useCallback(() => {
    if (index < products.length - 1) setIndex((i) => i + 1);
    else onClose();
  }, [index, products.length, onClose]);

  useEffect(() => {
    if (!autoplay) return;
    const id = window.setTimeout(advance, SPOTLIGHT_MS);
    return () => window.clearTimeout(id);
  }, [autoplay, advance]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        e.stopPropagation();
        if (index < products.length - 1) setIndex((i) => i + 1);
        else {
          onClose();
          replay.next();
        }
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
        replay.prev();
      } else if (e.key === " ") {
        // Space pauses where we are: stop the countdown, stop the replay.
        e.preventDefault();
        e.stopPropagation();
        setAutoplay(false);
        if (replay.playing) replay.toggle();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [index, products.length, onClose, replay]);

  if (!product || !viewer) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Just built: ${product.title}`}
      data-replay-spotlight
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4 animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="flex h-[86vh] w-[min(1100px,94vw)] flex-col overflow-hidden rounded-xl border border-border bg-background shadow-2xl animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0 flex-1">
            <ViewerHeading
              target={{ type: "product", product }}
              eyebrow={
                <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-primary">
                  <Sparkles className="h-3.5 w-3.5" /> Just built
                  {products.length > 1 && (
                    <span className="text-muted-foreground">
                      · {index + 1} of {products.length}
                    </span>
                  )}
                </span>
              }
            />
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Close (Esc)"
            title="Close (Esc)"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        {products.length > 1 && (
          <nav className="flex gap-1 border-b border-border px-5 py-2" aria-label="Built on this step">
            {products.map((p, i) => (
              <button
                key={p.id}
                type="button"
                onClick={() => {
                  setAutoplay(false);
                  setIndex(i);
                }}
                className={cn(
                  "truncate rounded px-2 py-0.5 text-xs",
                  i === index
                    ? "bg-primary/15 font-medium text-primary"
                    : "text-muted-foreground hover:bg-accent",
                )}
              >
                {p.title}
              </button>
            ))}
          </nav>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <ProductBody product={product} run={viewer.run} mediaHeight="58vh" onTalk={viewer.talkTo} />
        </div>
        <footer className="relative flex items-center gap-3 border-t border-border px-5 py-2.5 text-[11px] text-muted-foreground">
          {autoplay && (
            <span
              key={product.id}
              className="absolute left-0 top-0 h-0.5 bg-primary"
              style={{ animation: `spotlight-progress ${SPOTLIGHT_MS}ms linear forwards` }}
            />
          )}
          <span>
            {autoplay ? "Space to hold here" : "→ next · ← back · Esc close"}
          </span>
          <button
            type="button"
            onClick={() => {
              if (index < products.length - 1) {
                setAutoplay(false);
                setIndex((i) => i + 1);
              } else {
                onClose();
                if (!autoplay) replay.next();
              }
            }}
            className="ml-auto inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-foreground hover:bg-accent"
          >
            {index < products.length - 1 ? "Next" : "Continue"}
            <ChevronRight className="h-3 w-3" />
          </button>
        </footer>
      </div>
      <style>{`@keyframes spotlight-progress { from { width: 0% } to { width: 100% } }`}</style>
    </div>
  );
}
