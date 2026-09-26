import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import type { PDFDocumentProxy } from "pdfjs-dist/legacy/build/pdf.mjs";

interface Props {
  /** Object URL of the PDF (from the view cache). */
  src: string;
  /** "Slide" for a deck, "Page" for any other PDF. */
  unit?: "Slide" | "Page";
  /** Max height of the rendered page. */
  maxHeight?: string;
}

/**
 * A PDF drawn one page at a time — for a deck, one slide at a time, the way
 * you would show it to a room.
 *
 * Replaces an `<iframe src=blob:…pdf>`, which leaned on the browser's own PDF
 * viewer: absent in headless Chromium and on iOS (the frame came up blank on
 * the first deploy check), and even where present it is a document viewer —
 * toolbar, page scroll, zoom — inside a dialog, not a slide.
 *
 * pdf.js is imported on first use so it costs nothing until someone opens a
 * PDF. Navigation is buttons only, never arrow keys: the replay spotlight owns
 * → / ← for stepping the run.
 */
export function PdfSlides({ src, unit = "Page", maxHeight = "62vh" }: Props) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    let loading: { destroy: () => Promise<void> } | null = null;
    setDoc(null);
    setPage(1);
    setError(null);
    void (async () => {
      try {
        // The LEGACY build: pdf.js 6's modern build calls Math.sumPrecise,
        // which only the newest browsers have (it logged "Math.sumPrecise is
        // not a function" on the first deploy check). Legacy polyfills it.
        const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
        const worker = await import("pdfjs-dist/legacy/build/pdf.worker.min.mjs?url");
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
        const task = pdfjs.getDocument({ url: src });
        loading = task;
        const loaded = await task.promise;
        if (!cancelled) setDoc(loaded);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
      void loading?.destroy();
    };
  }, [src]);

  useEffect(() => {
    if (!doc || !canvasRef.current || !boxRef.current) return;
    let cancelled = false;
    let task: { cancel: () => void } | null = null;
    void (async () => {
      const p = await doc.getPage(page);
      if (cancelled || !canvasRef.current || !boxRef.current) return;
      const base = p.getViewport({ scale: 1 });
      // Fit the whole page: as wide as the box, unless that makes it taller
      // than the height cap — then as tall as the cap allows.
      const boxWidth = boxRef.current.clientWidth || base.width;
      const capHeight = toPixels(maxHeight);
      const width = Math.min(boxWidth, (capHeight * base.width) / base.height);
      // Crisp on retina: render at devicePixelRatio, display at CSS width.
      const ratio = window.devicePixelRatio || 1;
      const viewport = p.getViewport({ scale: (width / base.width) * ratio });
      const canvas = canvasRef.current;
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = `${viewport.width / ratio}px`;
      const render = p.render({ canvas, viewport });
      task = render;
      await render.promise.catch(() => undefined);
    })();
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [doc, page, maxHeight]);

  if (error) {
    return <p className="p-4 text-sm text-muted-foreground">Couldn't draw this file ({error}).</p>;
  }

  const total = doc?.numPages ?? 0;
  return (
    <div className="flex flex-col gap-2">
      <div
        ref={boxRef}
        className="flex w-full items-center justify-center overflow-hidden rounded border border-border bg-white"
        style={{ maxHeight }}
      >
        {!doc && <p className="p-8 text-sm text-neutral-500">Opening…</p>}
        <canvas ref={canvasRef} aria-label={`${unit} ${page}`} />
      </div>
      {total > 1 && (
        <div className="flex items-center justify-center gap-3 text-xs text-muted-foreground">
          <button
            type="button"
            onClick={() => setPage((n) => Math.max(1, n - 1))}
            disabled={page <= 1}
            className="rounded border border-border p-1 hover:bg-accent disabled:opacity-40"
            aria-label={`Previous ${unit.toLowerCase()}`}
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="tabular-nums">
            {unit} {page} of {total}
          </span>
          <button
            type="button"
            onClick={() => setPage((n) => Math.min(total, n + 1))}
            disabled={page >= total}
            className="rounded border border-border p-1 hover:bg-accent disabled:opacity-40"
            aria-label={`Next ${unit.toLowerCase()}`}
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  );
}

/** A CSS length in `vh` or `px` as pixels, for sizing the canvas. */
function toPixels(length: string): number {
  const n = parseFloat(length);
  if (length.endsWith("vh")) return (window.innerHeight * n) / 100;
  return Number.isFinite(n) ? n : window.innerHeight * 0.6;
}
