import { useEffect, useMemo, useRef, useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";
import type { ClipObject } from "../../types";
import {
  listMediaLibraryVideo,
  type MediaLibraryVideoOut,
} from "@/api/videos";

interface Props {
  clipKind: "scene-clip" | "product-beat";
  index: number;
  onCommit: () => void;
  onCancel: () => void;
}

function aliasFromRef(r: string): string | null {
  return r.startsWith("@") ? r.slice(1) : null;
}

// Format seconds as m:ss.t for human-readable durations on tiles.
function fmtDuration(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = secs - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

interface Tile {
  subfolder: string;
  filename: string;
  alias: string;
  inProgram: boolean;
  isCurrent: boolean;
  name: string | null;
  // Count of OTHER slots in this spec already using this alias (not
  // counting the slot being edited). Helps the user spot that picking
  // it here will orphan the alias from one place but keep it used
  // elsewhere — useful context, not a hard block.
  usedByOtherCount: number;
}

type FilterKey = "all" | "in-program" | "field-broll" | "mobile-screencast" | "web-screencast";

const FILTER_LABELS: Record<FilterKey, string> = {
  all: "All",
  "in-program": "This program",
  "field-broll": "Field b-roll",
  "mobile-screencast": "Mobile app",
  "web-screencast": "Web dashboard",
};

// Which subfolders make sense for each slot kind. scene-clip is the
// "Field footage" beat — b-roll only. product-beat is the "Connect
// app walkthrough" beat — phone or web screencasts. Picking a
// mismatched kind isn't blocked (the renderer accepts it), but the
// tile flags the mismatch so the user notices before clicking.
const EXPECTED_SUBFOLDERS: Record<Props["clipKind"], string[]> = {
  "scene-clip": ["field-broll"],
  "product-beat": ["mobile-screencast", "web-screencast"],
};

// Count how many times each alias appears across scene.clips and
// product.beats in the current spec, excluding the slot being edited.
// Used for the "Used elsewhere" hint on tiles.
function countAliasUsages(
  spec: { scene?: { clips: (string | ClipObject)[] }; product?: { beats: (string | ClipObject)[] } },
  excludeKind: Props["clipKind"],
  excludeIndex: number,
): Record<string, number> {
  const counts: Record<string, number> = {};
  const walk = (clips: (string | ClipObject)[] | undefined, kind: Props["clipKind"]) => {
    if (!clips) return;
    clips.forEach((slot, i) => {
      if (kind === excludeKind && i === excludeIndex) return;
      const ref = typeof slot === "string" ? slot : slot.asset;
      const alias = aliasFromRef(ref);
      if (alias) counts[alias] = (counts[alias] ?? 0) + 1;
    });
  };
  walk(spec.scene?.clips, "scene-clip");
  walk(spec.product?.beats, "product-beat");
  return counts;
}

export function ClipPickerPanel({ clipKind, index, onCommit, onCancel }: Props) {
  const { effectiveSpec, workspaceSlug, dispatch } = useBeatEditor();

  const slot = clipKind === "scene-clip"
    ? effectiveSpec.scene?.clips[index]
    : effectiveSpec.product?.beats[index];
  const currentRef = typeof slot === "string" ? slot : slot?.asset ?? "";
  const currentAlias = aliasFromRef(currentRef);

  const manifest = effectiveSpec.manifest ?? {};

  // Default filter — picked once when the library lands. Heuristic:
  //   1. If we can resolve the current clip to a library entry, use
  //      its subfolder (so swapping @web-superset-graphs opens on
  //      "Web dashboard", not the slot-kind guess).
  //   2. Otherwise fall back to a slot-kind heuristic: scene-clip →
  //      Field b-roll, product-beat → Mobile app.
  const fallbackFilter: FilterKey =
    clipKind === "scene-clip" ? "field-broll" : "mobile-screencast";
  const [filter, setFilter] = useState<FilterKey>(fallbackFilter);
  const [data, setData] = useState<MediaLibraryVideoOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const filterInitialized = useRef(false);

  // Per-tile loaded duration (in seconds), keyed by "subfolder/filename".
  // Captured from <video onLoadedMetadata> as each tile's metadata loads.
  const [durations, setDurations] = useState<Record<string, number>>({});

  useEffect(() => {
    let cancelled = false;
    listMediaLibraryVideo(workspaceSlug)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        // Once we know the library, re-pick the default filter using
        // the current clip's actual subfolder (if it's in the lib).
        // Only fires once per mount so the user's own filter clicks
        // aren't overridden.
        if (!filterInitialized.current && currentAlias) {
          for (const sub of d.subfolders) {
            for (const item of sub.items) {
              const a = item.filename.replace(/\.[^.]+$/, "");
              if (a === currentAlias) {
                const key = sub.subfolder as FilterKey;
                if (key === "field-broll" || key === "mobile-screencast" || key === "web-screencast") {
                  setFilter(key);
                }
                break;
              }
            }
          }
        }
        filterInitialized.current = true;
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [workspaceSlug, currentAlias]);

  // Other-slot usage counts. Memoized so we don't re-walk the spec on
  // every render.
  const usageCounts = useMemo(
    () => countAliasUsages(effectiveSpec, clipKind, index),
    [effectiveSpec, clipKind, index],
  );

  const allTiles: Tile[] = useMemo(() => {
    if (!data) return [];
    const rows: Tile[] = [];
    for (const sub of data.subfolders) {
      for (const item of sub.items) {
        const alias = item.filename.replace(/\.[^.]+$/, "");
        rows.push({
          subfolder: sub.subfolder,
          filename: item.filename,
          alias,
          inProgram: alias in manifest,
          isCurrent: alias === currentAlias,
          name: item.name,
          usedByOtherCount: usageCounts[alias] ?? 0,
        });
      }
    }
    return rows;
  }, [data, manifest, currentAlias, usageCounts]);

  // "In manifest" badge is only useful when the library has MORE
  // entries than the manifest does — otherwise every non-current tile
  // would carry the badge as redundant noise. Show it only when
  // there's at least one library-only tile.
  const showInManifestBadge = useMemo(
    () => allTiles.some((t) => !t.inProgram),
    [allTiles],
  );

  const tiles: Tile[] = useMemo(() => {
    let xs = allTiles;
    if (filter === "in-program") {
      xs = xs.filter((t) => t.inProgram);
    } else if (filter === "field-broll" || filter === "mobile-screencast" || filter === "web-screencast") {
      xs = xs.filter((t) => t.subfolder === filter);
    }
    return [...xs].sort((a, b) => {
      if (a.isCurrent !== b.isCurrent) return a.isCurrent ? -1 : 1;
      if (a.inProgram !== b.inProgram) return a.inProgram ? -1 : 1;
      return a.alias.localeCompare(b.alias);
    });
  }, [allTiles, filter]);

  const prefix = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const streamUrl = (sub: string, filename: string) =>
    `${prefix}/api/w/${workspaceSlug}/videos/library/${"video"}/${sub}/${filename}/stream`;

  const swap = (tile: Tile) => {
    if (tile.isCurrent) {
      onCancel();
      return;
    }
    if (tile.inProgram) {
      dispatch({
        type: "APPEND_OP",
        op: { op: "set-clip-asset", kind: clipKind, index, alias: tile.alias },
      });
    } else {
      dispatch({
        type: "APPEND_OP",
        op: {
          op: "set-clip-asset", kind: clipKind, index,
          ref: `library:video/${tile.subfolder}/${tile.filename}`,
        },
      });
    }
    onCommit();
  };

  const filterCount = (key: FilterKey): number => {
    if (key === "all") return allTiles.length;
    if (key === "in-program") return allTiles.filter((t) => t.inProgram).length;
    return allTiles.filter((t) => t.subfolder === key).length;
  };

  // ---- Hover preview ---------------------------------------------------
  // Play the muted preview after a short hover delay so the user can
  // see the clip's content without clicking. Pause + reset on leave so
  // the next hover starts from frame 0. We track ONE hovered tile at a
  // time via state; the <video> refs let us call play/pause directly.
  const videoRefs = useRef<Record<string, HTMLVideoElement | null>>({});
  const hoverTimer = useRef<number | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current);
    };
  }, []);

  const onTileEnter = (key: string) => {
    setHovered(key);
    if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current);
    hoverTimer.current = window.setTimeout(() => {
      const v = videoRefs.current[key];
      if (v) {
        try { v.currentTime = 0; } catch { /* swallow */ }
        v.play().catch(() => { /* autoplay blocked, ignore */ });
      }
    }, 250);
  };
  const onTileLeave = (key: string) => {
    if (hoverTimer.current !== null) window.clearTimeout(hoverTimer.current);
    setHovered((h) => (h === key ? null : h));
    const v = videoRefs.current[key];
    if (v) {
      v.pause();
      try { v.currentTime = 0; } catch { /* swallow */ }
    }
  };

  if (error) {
    return (
      <div className="rounded border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
        Couldn't load library: {error}
      </div>
    );
  }

  if (!data) {
    return <div className="text-sm text-muted-foreground">Loading library…</div>;
  }

  const expectedSubs = EXPECTED_SUBFOLDERS[clipKind];

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted-foreground">
        Pick a clip from the workspace library. Selecting one outside this
        program's manifest auto-adds the manifest entry — no separate edit
        needed.
      </div>

      <div className="flex flex-wrap gap-1.5">
        {(["all", "in-program", "field-broll", "mobile-screencast", "web-screencast"] as FilterKey[]).map((key) => {
          const count = filterCount(key);
          const isActive = filter === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              disabled={count === 0}
              className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                isActive
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-muted hover:border-primary"
              } disabled:opacity-40`}
            >
              {FILTER_LABELS[key]} <span className="opacity-70">{count}</span>
            </button>
          );
        })}
      </div>

      {tiles.length === 0 ? (
        <div className="rounded border border-dashed bg-muted/20 p-4 text-xs text-muted-foreground">
          No clips match this filter.
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {tiles.map((tile) => {
            const key = `${tile.subfolder}/${tile.filename}`;
            const mismatched = !expectedSubs.includes(tile.subfolder);
            const dur = durations[key];
            return (
              <button
                type="button"
                key={key}
                onClick={() => swap(tile)}
                onMouseEnter={() => onTileEnter(key)}
                onMouseLeave={() => onTileLeave(key)}
                onFocus={() => onTileEnter(key)}
                onBlur={() => onTileLeave(key)}
                className={`flex flex-col gap-2 rounded border p-2 text-left transition-colors ${
                  tile.isCurrent
                    ? "border-primary bg-primary/5"
                    : mismatched
                      ? "border-amber-500/40 hover:border-amber-500"
                      : "border-muted hover:border-primary"
                }`}
              >
                <div className="relative">
                  <video
                    ref={(el) => { videoRefs.current[key] = el; }}
                    src={streamUrl(tile.subfolder, tile.filename)}
                    preload="metadata"
                    muted
                    playsInline
                    loop
                    onLoadedMetadata={(e) => {
                      const d = e.currentTarget.duration;
                      if (Number.isFinite(d) && d > 0) {
                        setDurations((prev) => prev[key] === d ? prev : { ...prev, [key]: d });
                      }
                    }}
                    className="h-24 w-full rounded bg-black object-cover"
                  />
                  {tile.isCurrent && (
                    <span className="absolute right-1 top-1 rounded-full bg-primary px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary-foreground">
                      Current
                    </span>
                  )}
                  {!tile.isCurrent && tile.inProgram && showInManifestBadge && (
                    <span className="absolute right-1 top-1 rounded-full bg-muted/90 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-foreground">
                      In manifest
                    </span>
                  )}
                  {!tile.isCurrent && !tile.inProgram && (
                    <span className="absolute right-1 top-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
                      Library
                    </span>
                  )}
                  {/* Source duration in the bottom-left so the user sees
                      how much material they're picking — a 60s clip into a
                      2.3s slot means only 4% plays. */}
                  {dur !== undefined && (
                    <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[10px] text-white">
                      {fmtDuration(dur)}
                    </span>
                  )}
                  {/* Hover indicator — the muted clip starts playing
                      after a 250ms delay, but a subtle outline on the
                      thumbnail confirms the hover registered. */}
                  {hovered === key && (
                    <span className="pointer-events-none absolute inset-0 rounded ring-2 ring-primary/40" />
                  )}
                </div>
                {tile.name && (
                  <div className="line-clamp-2 text-xs font-medium text-foreground">
                    {tile.name}
                  </div>
                )}
                <div className="flex items-center justify-between gap-2">
                  <code className="rounded bg-muted px-1.5 py-0.5 text-[11px]">@{tile.alias}</code>
                  <span className="text-[10px] text-muted-foreground">{tile.subfolder}</span>
                </div>
                {(mismatched || tile.usedByOtherCount > 0) && (
                  <div className="flex flex-wrap gap-1.5 text-[10px]">
                    {mismatched && (
                      <span
                        className="rounded bg-amber-500/15 px-1.5 py-0.5 font-medium text-amber-700 dark:text-amber-400"
                        title={`This slot's beat usually wants ${expectedSubs.join(" or ")}, but this clip is from ${tile.subfolder}. The renderer will accept it; the result may not match the beat's visual intent.`}
                      >
                        ⚠ kind mismatch
                      </span>
                    )}
                    {tile.usedByOtherCount > 0 && (
                      <span
                        className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground"
                        title={`Used by ${tile.usedByOtherCount} other slot${tile.usedByOtherCount === 1 ? "" : "s"} in this spec.`}
                      >
                        used in {tile.usedByOtherCount} other slot{tile.usedByOtherCount === 1 ? "" : "s"}
                      </span>
                    )}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      )}

      <div className="mt-2 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded border px-3 py-1.5 text-sm"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
