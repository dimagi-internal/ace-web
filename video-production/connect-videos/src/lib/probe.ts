import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";

/**
 * Read media duration in seconds via ffprobe. Returns null when ffprobe
 * isn't installed, the file is missing, or the format is unreadable —
 * the renderer keeps going either way; sidecar metadata is best-effort.
 */
export function probeDurationSeconds(filePath: string): number | null {
  if (!existsSync(filePath)) return null;
  try {
    const out = execFileSync(
      "ffprobe",
      [
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        filePath,
      ],
      { encoding: "utf8", timeout: 5_000 },
    ).trim();
    const n = Number(out);
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}
