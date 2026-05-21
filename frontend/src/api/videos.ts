/**
 * Client for the workspace-scoped Videos API.
 *
 * Storage layout mirrors opps/runs:
 *   GET    /programs                            list programs (latest run summary)
 *   GET    /programs/{slug}                     detail incl. runs list
 *   POST   /programs/{slug}/runs                copy latest run → new run-NNN
 *   GET    /programs/{slug}/runs/{run_id}       run detail
 *   POST   /programs/{slug}/runs/{run_id}/build render or rebuild
 *   POST   /programs/{slug}/runs/{run_id}/edit  mutate the run's spec.yaml
 *   GET    /programs/{slug}/runs/{run_id}/render-status
 *   GET    /programs/{slug}/runs/{run_id}/explorer.html
 *   GET    /programs/{slug}/runs/{run_id}/media/{name}
 */

import type { ProgramSpec } from "@/components/videos/types";

const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");

function getCsrfToken(): string {
  if (typeof document === "undefined") return "";
  for (const raw of document.cookie.split(";")) {
    const [name, ...rest] = raw.trim().split("=");
    if (name === "csrftoken_ace" || name === "csrftoken") {
      return decodeURIComponent(rest.join("="));
    }
  }
  return "";
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

async function v2Fetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers ?? {});
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (UNSAFE.has(method)) {
    const token = getCsrfToken();
    if (token && !headers.has("X-CSRFToken")) headers.set("X-CSRFToken", token);
    if (!headers.has("Content-Type") && init.body) headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(API_PREFIX + path, { ...init, headers, credentials: "include" });
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = body.detail;
      else if (body?.title) detail = body.title;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

// ───────── types ─────────

export interface VideoProgramCard {
  slug: string;
  name: string;
  tagline: string | null;
  country_focus: string | null;
  status: string | null;
  program_url: string | null;
  manifest_count: number;
  has_explorer_build: boolean;
  latest_run_id: string | null;
  run_count: number;
}

export interface RunSummary {
  run_id: string;
  has_output: boolean;
  has_explorer_build: boolean;
}

export interface VideoProgramDetail {
  slug: string;
  name: string;
  tagline: string | null;
  country_focus: string | null;
  status: string | null;
  program_url: string | null;
  runs: RunSummary[];
}

export interface RunDetail {
  program_slug: string;
  run_id: string;
  name: string;
  manifest_count: number;
  has_output: boolean;
  has_explorer_build: boolean;
  explorer_url: string;
  yaml_path: string;
  spec: ProgramSpec | null;
  // ISO-8601 mtime of final.mp4 — null when no render exists.
  // VideoExplorerPage's RunSummaryLine renders this as "rendered Nm ago"
  // so the user knows how fresh the embedded player's video is.
  output_rendered_at: string | null;
  // ISO-8601 modifiedTime of spec.yaml in Drive. RunSummaryLine
  // compares against output_rendered_at and shows "stale (edited
  // since)" when the saved spec is newer than the embedded video.
  spec_modified_at: string | null;
}

export interface RenderStatus {
  program_slug: string;
  run_id: string;
  busy: boolean;
  started_at: string | null;
  // True when the in-container render chain spawned but the sentinel
  // (explorer/index.html) hasn't appeared after the longest-plausible
  // render window. UI shows the captured render-log so the user can
  // recover (the Mac-host case has a known signature + a known fix —
  // see VideoExplorerPage's render-error block).
  appears_failed?: boolean;
}

export interface RenderLogResult {
  program_slug: string;
  run_id: string;
  started_at: string | null;
  log: string;
  size: number;
}

export interface CopyRunResult {
  program_slug: string;
  new_run_id: string;
  copied_from: string;
}

export interface BuildResult {
  ok: boolean;
  triggered: boolean;
  mode: "render" | "build-only";
  message: string;
}

// ───────── endpoints ─────────

const base = (ws: string) => `/api/w/${ws}/videos`;
const programBase = (ws: string, p: string) => `${base(ws)}/programs/${p}`;
const runBase = (ws: string, p: string, r: string) => `${programBase(ws, p)}/runs/${r}`;

export function listVideoPrograms(ws: string): Promise<VideoProgramCard[]> {
  return v2Fetch(`${base(ws)}/programs`);
}

export function getVideoProgram(ws: string, p: string): Promise<VideoProgramDetail> {
  return v2Fetch(programBase(ws, p));
}

export function getVideoRun(ws: string, p: string, r: string): Promise<RunDetail> {
  return v2Fetch(runBase(ws, p, r));
}

export function getRenderStatus(ws: string, p: string, r: string): Promise<RenderStatus> {
  return v2Fetch(`${runBase(ws, p, r)}/render-status`);
}

export function getRenderLog(ws: string, p: string, r: string): Promise<RenderLogResult> {
  return v2Fetch(`${runBase(ws, p, r)}/render-log`);
}

export function copyRun(ws: string, p: string): Promise<CopyRunResult> {
  return v2Fetch(`${programBase(ws, p)}/runs`, { method: "POST" });
}

export function triggerBuild(
  ws: string,
  p: string,
  r: string,
  mode: "render" | "build-only" = "render",
): Promise<BuildResult> {
  return v2Fetch(`${runBase(ws, p, r)}/build`, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

// ───────── edit-batch ─────────

export type EditBatchOp =
  | { op: "set-clip-trim"; kind: "scene-clip" | "product-beat"; index: number;
      start_seconds: number; duration_seconds: number }
  | { op: "set-clip-asset"; kind: "scene-clip" | "product-beat"; index: number;
      // Provide one of: `alias` (existing manifest entry) or `ref`
      // ("library:video/<sub>/<filename>" — server auto-adds to
      // manifest before swapping).
      alias?: string; ref?: string }
  | { op: "set-narration"; beatId: string; text: string }
  | { op: "set-stat"; path: string; big?: string; caption?: string; source?: string }
  | { op: "set-global-template"; tagline?: string; cycle_steps?: string[] }
  | { op: "set-program-name"; name: string };

export interface EditBatchResult {
  ok: boolean;
  applied: number;
  message: string;
}

export function submitEditBatch(
  ws: string, p: string, r: string, ops: EditBatchOp[],
): Promise<EditBatchResult> {
  return v2Fetch(`${runBase(ws, p, r)}/edit-batch`, {
    method: "POST",
    body: JSON.stringify({ ops }),
  });
}

// ───────── media library ─────────

export interface MediaLibraryVideoItemOut {
  ref: string;
  drive_id: string;
  drive_url: string;
  filename: string;
  name: string | null;
  description: string | null;
  tags: string[];
  status: string;
}

export interface MediaLibraryVideoSubfolderOut {
  subfolder: string;
  items: MediaLibraryVideoItemOut[];
}

export interface MediaLibraryVideoOut {
  subfolders: MediaLibraryVideoSubfolderOut[];
}

export interface MediaLibraryAudioItemOut {
  hash: string;
  drive_id: string;
  drive_url: string;
  voice_id: string | null;
  model: string | null;
  text: string | null;
  duration_sec: number | null;
  generated_at: string | null;
  status: string;
}

export interface MediaLibraryAudioOut {
  items: MediaLibraryAudioItemOut[];
}

export function listMediaLibraryVideo(ws: string): Promise<MediaLibraryVideoOut> {
  return v2Fetch(`${base(ws)}/library/video`);
}

export function listMediaLibraryAudio(ws: string): Promise<MediaLibraryAudioOut> {
  return v2Fetch(`${base(ws)}/library/audio`);
}
