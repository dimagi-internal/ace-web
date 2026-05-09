/**
 * Module-scoped per-tab cache for opp data, keyed by slug + runId.
 *
 * The backend serves the source-of-truth for staleness via Drive
 * Changes API + ETag. This cache simply remembers the last response
 * and its ETag so subsequent fetches send `If-None-Match` and skip the
 * body when nothing changed.
 *
 * No persistence to localStorage — correctness in the face of stale
 * localStorage isn't worth the complexity. Cache dies on tab close,
 * which is fine.
 */
import type { OppCard, OppSnapshot } from "./types";

export type Entry<T> = { data: T; etag: string };

const oppSnapshots = new Map<string, Entry<OppSnapshot>>();
const oppLists = new Map<string, Entry<OppCard[]>>();

function snapshotKey(slug: string, runId: string | null | undefined): string {
  return `${slug}:${runId ?? ""}`;
}

export function getCachedSnapshot(
  slug: string,
  runId: string | null | undefined,
): Entry<OppSnapshot> | undefined {
  return oppSnapshots.get(snapshotKey(slug, runId));
}

export function setCachedSnapshot(
  slug: string,
  runId: string | null | undefined,
  entry: Entry<OppSnapshot>,
): void {
  oppSnapshots.set(snapshotKey(slug, runId), entry);
}

export function dropOpp(slug: string): void {
  // Drop every cached entry for this slug regardless of runId.
  for (const key of Array.from(oppSnapshots.keys())) {
    if (key.startsWith(`${slug}:`)) {
      oppSnapshots.delete(key);
    }
  }
  // Also drop any list cache (a list entry contains this opp).
  oppLists.clear();
}

export function getCachedList(key: string): Entry<OppCard[]> | undefined {
  return oppLists.get(key);
}

export function setCachedList(key: string, entry: Entry<OppCard[]>): void {
  oppLists.set(key, entry);
}

export function dropList(key: string): void {
  oppLists.delete(key);
}

export function clearAll(): void {
  oppSnapshots.clear();
  oppLists.clear();
}
