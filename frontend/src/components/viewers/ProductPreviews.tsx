import { useEffect, useState } from "react";
import { ImageOff } from "lucide-react";

import type { ProductPreview } from "@/api/types.ws";
import { cn } from "@/lib/utils";

import { loadView } from "./viewCache";
import { useViewer } from "./ViewerContext";

interface Props {
  previews: readonly ProductPreview[];
  /** What the screenshots are of, for alt text and the opened view's title. */
  of: string;
  /** Rail size: a single row of small thumbnails, the rest counted. */
  compact?: boolean;
}

/** Thumbnails shown in the compact (rail) row before "+N". */
const COMPACT_MAX = 4;

/**
 * Screenshots of a product — the Learn app on a phone, a labs dashboard — as
 * thumbnails that open full size in the viewer.
 *
 * They are fetched through the run's view endpoint and the viewer's session
 * cache, so a thumbnail and the full-size view share one download, and a
 * screenshot the replay warmed is already there.
 */
export function ProductPreviews({ previews, of, compact = false }: Props) {
  const viewer = useViewer();
  if (previews.length === 0 || !viewer) return null;
  const shown = compact ? previews.slice(0, COMPACT_MAX) : previews;
  const more = previews.length - shown.length;

  const open = (p: ProductPreview) =>
    viewer.open({
      type: "file",
      fileId: p.file_id,
      name: p.name,
      title: p.caption ?? `${of} — screenshot`,
      skill: p.captured_by,
    });

  return (
    <ul
      aria-label={`Screenshots of ${of}`}
      className={cn(
        // Every frame at one height, each at its own width: a phone screen
        // stays narrow and a landscape dashboard gets the room it needs. A
        // fixed grid cell sized for phones drew a dashboard as a sliver.
        compact ? "flex items-center gap-1.5" : "flex flex-wrap items-start gap-3",
      )}
    >
      {shown.map((p) => (
        <li key={p.file_id} className={compact ? "shrink-0" : "flex max-w-full flex-col gap-1"}>
          <button
            type="button"
            onClick={() => open(p)}
            title={p.caption ?? p.name}
            className={cn(
              "block overflow-hidden rounded border border-border bg-muted/30 transition-colors hover:border-primary/60",
              compact ? "h-14" : "h-72",
            )}
          >
            <Thumb
              url={viewer.run.viewUrl(p.file_id)}
              alt={p.caption ?? `${of} screenshot`}
              compact={compact}
            />
          </button>
          {!compact && p.caption && (
            // `w-0 min-w-full`: the caption wraps to the IMAGE's width rather
            // than widening the item to fit its own text.
            <span className="line-clamp-3 w-0 min-w-full text-[11px] leading-snug text-muted-foreground">
              {p.caption}
            </span>
          )}
        </li>
      ))}
      {more > 0 && (
        <li className="text-[10px] tabular-nums text-muted-foreground" aria-label={`${more} more`}>
          +{more}
        </li>
      )}
    </ul>
  );
}

/** Keeps the screenshot's own shape — a phone screen is portrait, a labs
 *  dashboard landscape — rather than cropping both to one box. */
function Thumb({ url, alt, compact }: { url: string; alt: string; compact: boolean }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setSrc(null);
    setFailed(false);
    loadView(url).then((r) => {
      if (cancelled) return;
      if (r.kind === "image") setSrc(r.objectUrl);
      else setFailed(true);
    });
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (failed) {
    return (
      <span className="flex h-full min-w-9 items-center justify-center px-2 text-muted-foreground/60">
        <ImageOff className="h-3.5 w-3.5" aria-label="Screenshot unavailable" />
      </span>
    );
  }
  if (!src) {
    return (
      <span className={cn("block h-full animate-pulse bg-muted/60", compact ? "w-9" : "w-40")} aria-hidden />
    );
  }
  return (
    <img
      src={src}
      alt={alt}
      className={
        compact ? "h-full w-auto max-w-24 object-cover object-top" : "h-full w-auto max-w-none"
      }
    />
  );
}
