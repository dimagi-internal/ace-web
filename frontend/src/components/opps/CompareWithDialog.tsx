import { useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { GitCompareArrows } from "lucide-react";

import type { OppCard } from "@/api/types.ws";
import { Button } from "@canopy/workbench/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  source: OppCard;
  candidates: OppCard[];
}

/**
 * Picker for choosing the second opp in a side-by-side comparison.
 * Tag-siblings (opps sharing at least one tag with `source`) are
 * shown first; everything else is alphabetical underneath.
 */
export function CompareWithDialog({ open, onOpenChange, source, candidates }: Props) {
  const navigate = useNavigate();
  const { workspaceSlug } = useParams<{ workspaceSlug: string }>();

  const sortedCandidates = useMemo(() => {
    const sourceTags = new Set(source.tags);
    const others = candidates.filter((c) => c.slug !== source.slug);
    const siblings = others.filter((c) => c.tags.some((t) => sourceTags.has(t)));
    const siblingSlugs = new Set(siblings.map((s) => s.slug));
    const rest = others.filter((c) => !siblingSlugs.has(c.slug));
    siblings.sort((a, b) => a.slug.localeCompare(b.slug));
    rest.sort((a, b) => a.slug.localeCompare(b.slug));
    return { siblings, rest };
  }, [source, candidates]);

  const goCompare = (otherSlug: string) => {
    onOpenChange(false);
    const wsBase = workspaceSlug ? `/w/${workspaceSlug}` : "";
    navigate(
      `${wsBase}/opps/compare/${encodeURIComponent(source.slug)}/${encodeURIComponent(otherSlug)}`,
    );
  };

  const noOptions =
    sortedCandidates.siblings.length === 0 && sortedCandidates.rest.length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            <span className="inline-flex items-center gap-2">
              <GitCompareArrows className="h-4 w-4" />
              Compare with…
            </span>
          </DialogTitle>
          <DialogDescription>
            Pick another opportunity to see a side-by-side comparison with{" "}
            <span className="font-mono">{source.slug}</span>.
          </DialogDescription>
        </DialogHeader>

        {noOptions ? (
          <p className="py-4 text-sm text-muted-foreground">
            This is the only opportunity in your workspace — create another one
            to enable comparisons.
          </p>
        ) : (
          <div className="max-h-80 overflow-y-auto">
            {sortedCandidates.siblings.length > 0 && (
              <div className="mb-2">
                <div className="px-1 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Tag-siblings
                </div>
                <ul className="space-y-1">
                  {sortedCandidates.siblings.map((c) => (
                    <CandidateRow
                      key={c.slug}
                      candidate={c}
                      onPick={() => goCompare(c.slug)}
                    />
                  ))}
                </ul>
              </div>
            )}
            {sortedCandidates.rest.length > 0 && (
              <div>
                {sortedCandidates.siblings.length > 0 && (
                  <div className="px-1 pb-1.5 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Other opps
                  </div>
                )}
                <ul className="space-y-1">
                  {sortedCandidates.rest.map((c) => (
                    <CandidateRow
                      key={c.slug}
                      candidate={c}
                      onPick={() => goCompare(c.slug)}
                    />
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CandidateRow({
  candidate,
  onPick,
}: {
  candidate: OppCard;
  onPick: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        className="flex w-full items-center justify-between gap-3 rounded border border-border bg-card px-3 py-2 text-left text-sm transition hover:border-primary"
      >
        <div className="min-w-0">
          <div className="truncate font-medium text-foreground">
            {candidate.display_name || candidate.slug}
          </div>
          <div className="truncate font-mono text-xs text-muted-foreground">
            {candidate.slug}
          </div>
        </div>
        {candidate.eval_score != null && (
          <span
            className={
              "shrink-0 rounded px-2 py-0.5 text-xs font-medium " +
              (candidate.eval_passed === true
                ? "bg-emerald-900/60 text-emerald-200"
                : candidate.eval_passed === false
                  ? "bg-red-900/60 text-red-200"
                  : "bg-muted text-muted-foreground")
            }
          >
            {candidate.eval_score > 10
              ? `${candidate.eval_score.toFixed(0)}/100`
              : `${candidate.eval_score.toFixed(1)}/10`}
          </span>
        )}
      </button>
    </li>
  );
}
