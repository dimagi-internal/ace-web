import type { OppCard } from "../api/types.ws";

export type SortKey = "recent" | "score" | "status" | "slug";

// Each option: short label that fits the dropdown width + a longer
// title attribute explaining the sort key, so a new user can hover to
// see what "Status" actually orders by. Avoid the word "slug" in the
// option label itself — name it "ID" since users see the slug as the
// stable identifier.
export const SORT_OPTIONS: { key: SortKey; label: string; title: string }[] = [
  { key: "recent", label: "Last activity", title: "Most recently active opps first" },
  { key: "score", label: "Score (high → low)", title: "Highest opp-eval scores first; opps without a score sink to the bottom" },
  { key: "status", label: "Needs attention", title: "Load failures first, then opps without state, then everything else" },
  { key: "slug", label: "ID (A → Z)", title: "Alphabetical by opp identifier" },
];

// We rank opps the user is most likely to need to look at first:
// load failures, then opps with no state.yaml, then everything else.
const STATUS_RANK: Record<string, number> = {
  error: 0,
  "no-state": 1,
  ok: 2,
};

export function sortOpps(opps: OppCard[], key: SortKey): OppCard[] {
  const out = [...opps];
  switch (key) {
    case "recent":
      // "Last activity" = state.yaml's Drive modifiedTime (best cheap proxy
      // for "anything moved here"). Falls back to created_at when the opp
      // has no state.yaml yet.
      out.sort((a, b) => {
        const at = a.last_activity_at ?? a.created_at ?? "";
        const bt = b.last_activity_at ?? b.created_at ?? "";
        if (at === bt) return a.slug.localeCompare(b.slug);
        return bt.localeCompare(at);
      });
      break;
    case "score":
      out.sort((a, b) => {
        const av = a.eval_score ?? -1;
        const bv = b.eval_score ?? -1;
        if (av === bv) return a.slug.localeCompare(b.slug);
        return bv - av;
      });
      break;
    case "status":
      out.sort((a, b) => {
        const ar = STATUS_RANK[a.status] ?? 99;
        const br = STATUS_RANK[b.status] ?? 99;
        if (ar === br) return a.slug.localeCompare(b.slug);
        return ar - br;
      });
      break;
    case "slug":
      out.sort((a, b) => a.slug.localeCompare(b.slug));
      break;
  }
  return out;
}
