import { useBeatEditor } from "../BeatEditorContext";
import type { Stat } from "../types";

function resolveStat(
  spec: ReturnType<typeof useBeatEditor>["effectiveSpec"],
  path: string,
): Stat | null {
  if (path === "problem") return spec.problem ?? null;
  const m = /^impact\[(\d+)\]$/.exec(path);
  if (!m) return null;
  return spec.impact?.[parseInt(m[1], 10)] ?? null;
}

export function StatsWidget({ beatId, path }: { beatId: string; path: string }) {
  const { effectiveSpec, dispatch } = useBeatEditor();
  const stat = resolveStat(effectiveSpec, path);
  if (!stat) return null;
  return (
    <div
      className="cursor-pointer rounded border bg-muted/20 p-3 hover:border-primary"
      onClick={() => dispatch({ type: "OPEN_DRAWER", target: { kind: "stat", beatId, path } })}
    >
      <div className="flex items-baseline gap-3">
        <div className="text-3xl font-bold">{stat.big}</div>
        <div className="flex-1">
          <div className="text-sm">{stat.caption}</div>
          {stat.source && (
            <div className="mt-0.5 text-xs text-muted-foreground">source: {stat.source}</div>
          )}
        </div>
        <span className="text-xs text-muted-foreground">click to edit</span>
      </div>
    </div>
  );
}
