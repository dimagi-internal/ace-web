/**
 * Fetch-and-cache for the in-page file viewer.
 *
 * The view endpoint (`/artifacts/{id}/view`) answers with the representation
 * a browser can draw — markdown, CSV, PDF, image, video, text — and says
 * which in its Content-Type. This turns a response into something to render
 * and keeps it for the session, so a file the replay warmed ahead of time
 * pops up instantly instead of waiting on Drive in front of an audience.
 *
 * A failed load is NOT cached: the next open retries.
 */

export type ViewResult =
  | { kind: "markdown"; text: string; name: string | null; driveLink: string | null }
  | { kind: "csv"; rows: string[][]; truncated: boolean; name: string | null; driveLink: string | null }
  | { kind: "text"; text: string; name: string | null; driveLink: string | null }
  | {
      kind: "pdf" | "image" | "video";
      objectUrl: string;
      name: string | null;
      driveLink: string | null;
    }
  | { kind: "error"; status: number; message: string; driveLink: string | null };

/** Rows past this aren't rendered — a viewer, not a spreadsheet. */
export const MAX_CSV_ROWS = 500;

const cache = new Map<string, Promise<ViewResult>>();

export function loadView(url: string): Promise<ViewResult> {
  const hit = cache.get(url);
  if (hit) return hit;
  const pending = fetchView(url).then((result) => {
    if (result.kind === "error") cache.delete(url);
    return result;
  });
  cache.set(url, pending);
  return pending;
}

/** Warm several views one at a time — a background nicety, never a flood. */
export async function prefetchViews(urls: readonly string[], signal?: { cancelled: boolean }) {
  for (const url of urls) {
    if (signal?.cancelled) return;
    await loadView(url).catch(() => null);
  }
}

/** Test seam. */
export function clearViewCache() {
  cache.clear();
}

/** Views in flight at once. A product with 30 screenshots asks for 30 views
 *  the moment it opens; each is a ~1s Drive read on the server, and firing
 *  them all together once exhausted its DB pool and 503'd most of them. */
const MAX_IN_FLIGHT = 6;
/** Tries per view when the server answers 503 (busy, says retry). */
const MAX_TRIES = 3;

let inFlight = 0;
const waiting: (() => void)[] = [];

async function withSlot<T>(work: () => Promise<T>): Promise<T> {
  if (inFlight >= MAX_IN_FLIGHT) await new Promise<void>((resolve) => waiting.push(resolve));
  inFlight++;
  try {
    return await work();
  } finally {
    inFlight--;
    waiting.shift()?.();
  }
}

/** The server's Retry-After in ms, bounded so a tile never waits long. */
function retryDelayMs(response: Response): number {
  const seconds = Number(response.headers.get("Retry-After"));
  return Math.min(Number.isFinite(seconds) && seconds > 0 ? seconds : 2, 5) * 1000;
}

async function fetchView(url: string): Promise<ViewResult> {
  let response: Response;
  try {
    for (let attempt = 1; ; attempt++) {
      response = await withSlot(() => fetch(url, { credentials: "include" }));
      if (response.status !== 503 || attempt >= MAX_TRIES) break;
      const delay = retryDelayMs(response);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  } catch (e) {
    return { kind: "error", status: 0, message: String(e), driveLink: null };
  }
  const driveLink = response.headers.get("X-Drive-Link");
  const rawName = response.headers.get("X-Artifact-Name");
  const name = rawName ? safeDecode(rawName) : null;
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const problem = (await response.json()) as { title?: string; detail?: string };
      message = problem.title ?? message;
    } catch {
      // not a problem+json body; keep the status line
    }
    return { kind: "error", status: response.status, message, driveLink };
  }

  const type = (response.headers.get("Content-Type") ?? "").split(";")[0].trim().toLowerCase();
  if (type === "text/markdown") {
    return { kind: "markdown", text: await response.text(), name, driveLink };
  }
  if (type === "text/csv") {
    const all = parseCsv(await response.text());
    return {
      kind: "csv",
      rows: all.slice(0, MAX_CSV_ROWS),
      truncated: all.length > MAX_CSV_ROWS,
      name,
      driveLink,
    };
  }
  if (type === "application/pdf" || type.startsWith("image/") || type.startsWith("video/")) {
    const objectUrl = URL.createObjectURL(await response.blob());
    const kind = type === "application/pdf" ? "pdf" : type.startsWith("image/") ? "image" : "video";
    return { kind, objectUrl, name, driveLink };
  }
  return { kind: "text", text: await response.text(), name, driveLink };
}

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/** RFC 4180-ish: quoted fields, doubled quotes, CRLF or LF rows. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          quoted = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      quoted = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += c;
    }
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}
