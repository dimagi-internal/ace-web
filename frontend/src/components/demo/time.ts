/**
 * Time formatting for the Demo Player.
 *
 * Every readout here is elapsed wall time. The player reports no tokens and
 * no dollars — see docs/specs/2026-09-17-ace-demo-player-design.md, section
 * "No token or cost readout, anywhere in the player".
 */

/** `4:12:33` / `12:33` — for the big counters.
 *
 * `widestSeconds` is the largest value this counter will ever show. Pass it
 * and the clock formats to that width from the first tick, so a six-hour run
 * doesn't jump from `12:33` to `1:00:00` and shove the layout sideways in the
 * middle of a demo. Tabular figures handle the rest.
 */
export function clock(totalSeconds: number, widestSeconds?: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const widest = Math.max(s, Math.floor(widestSeconds ?? s));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const showHours = widest >= 3600;
  const mm = String(minutes).padStart(showHours ? 2 : 1, "0");
  const ss = String(seconds).padStart(2, "0");
  return showHours ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** `6h 14m` / `27m` / `45s` — for prose-adjacent durations in the ledger. */
export function duration(totalSeconds: number | null | undefined): string {
  if (totalSeconds === null || totalSeconds === undefined) return "—";
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) return `${s}s`;
  const hours = Math.floor(s / 3600);
  const minutes = Math.round((s % 3600) / 60);
  if (hours === 0) return `${minutes}m`;
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`;
}
