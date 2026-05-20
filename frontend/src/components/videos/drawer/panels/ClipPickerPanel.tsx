import { useEffect, useMemo, useState } from "react";
import { useBeatEditor } from "../../BeatEditorContext";
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

// Tile shown in the picker grid. Combines a library entry with the
// view-state we need to render badges + dispatch the right op:
//   inProgram = true means the alias is already in spec.manifest
//   isCurrent = true means this tile *is* the slot's current source
interface Tile {
  subfolder: string;
  filename: string;
  alias: string;          // derived from filename (stem)
  inProgram: boolean;
  isCurrent: boolean;
  name: string | null;
}

type FilterKey = "all" | "in-program" | "field-broll" | "mobile-screencast" | "web-screencast";

const FILTER_LABELS: Record<FilterKey, string> = {
  all: "All",
  "in-program": "This program",
  "field-broll": "Field b-roll",
  "mobile-screencast": "Mobile app",
  "web-screencast": "Web dashboard",
};

/**
 * Swap the source clip in a beat slot. Sourced from the workspace's
 * full video library (library/video/<subfolder>/*) — not just the
 * subset already in spec.manifest. Picking a clip outside the
 * manifest dispatches `set-clip-asset` with a `library:` ref, and the
 * server auto-inserts the matching manifest entry before setting the
 * slot's asset. Existing trim values are preserved.
 *
 * Filter pills:
 *   - All: every workspace library entry
 *   - This program: only entries already in spec.manifest
 *   - Field b-roll / Mobile app / Web dashboard: by subfolder
 *
 * Tiles render with a thumbnail (via the per-library streaming
 * endpoint /library/video/<sub>/<file>/stream — handles Drive
 * shortcuts), name, subfolder badge, and a "Current" badge on the
 * slot's existing source.
 */
export function ClipPickerPanel({ clipKind, index, onCommit, onCancel }: Props) {
  const { effectiveSpec, workspaceSlug, dispatch } = useBeatEditor();

  const slot = clipKind === "scene-clip"
    ? effectiveSpec.scene?.clips[index]
    : effectiveSpec.product?.beats[index];
  const currentRef = typeof slot === "string" ? slot : slot?.asset ?? "";
  const currentAlias = aliasFromRef(currentRef);

  const manifest = effectiveSpec.manifest ?? {};

  // Default filter — when swapping a scene-clip (b-roll) slot, start
  // on field-broll; product-beat slots typically want mobile/web. Falls
  // back to "all" if the slot kind doesn't pre-suggest a subfolder.
  const defaultFilter: FilterKey =
    clipKind === "scene-clip" ? "field-broll" : "all";
  const [filter, setFilter] = useState<FilterKey>(defaultFilter);
  const [data, setData] = useState<MediaLibraryVideoOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listMediaLibraryVideo(workspaceSlug)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [workspaceSlug]);

  // Flatten subfolders into Tile rows; mark which entries are already
  // in the program's manifest so the picker can show that distinction.
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
        });
      }
    }
    return rows;
  }, [data, manifest, currentAlias]);

  // Apply the active filter; sort current-first, then in-program, then
  // alphabetical by alias.
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
      // Existing manifest alias — cheap path: just set the slot's
      // asset to @alias. No manifest edit needed.
      dispatch({
        type: "APPEND_OP",
        op: { op: "set-clip-asset", kind: clipKind, index, alias: tile.alias },
      });
    } else {
      // Library entry not yet in this program's manifest — server
      // resolves the gdrive id and auto-inserts a manifest entry,
      // then sets the slot's asset.
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

  // Counts in the filter row so the user can see what each pill will
  // narrow down to.
  const filterCount = (key: FilterKey): number => {
    if (key === "all") return allTiles.length;
    if (key === "in-program") return allTiles.filter((t) => t.inProgram).length;
    return allTiles.filter((t) => t.subfolder === key).length;
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

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted-foreground">
        Pick a clip from the workspace library. Selecting one outside this
        program's manifest auto-adds the manifest entry — no separate edit
        needed.
      </div>

      {/* Filter pills */}
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
          {tiles.map((tile) => (
            <button
              type="button"
              key={`${tile.subfolder}/${tile.filename}`}
              onClick={() => swap(tile)}
              className={`flex flex-col gap-2 rounded border p-2 text-left transition-colors ${
                tile.isCurrent
                  ? "border-primary bg-primary/5"
                  : "border-muted hover:border-primary"
              }`}
            >
              <div className="relative">
                <video
                  src={streamUrl(tile.subfolder, tile.filename)}
                  preload="metadata"
                  muted
                  className="h-24 w-full rounded bg-black object-cover"
                />
                {tile.isCurrent && (
                  <span className="absolute right-1 top-1 rounded-full bg-primary px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary-foreground">
                    Current
                  </span>
                )}
                {!tile.isCurrent && tile.inProgram && (
                  <span className="absolute right-1 top-1 rounded-full bg-muted/90 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-foreground">
                    In manifest
                  </span>
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
            </button>
          ))}
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
