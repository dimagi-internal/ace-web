const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
// Use 30-day months / 365-day years. The point is a glanceable label,
// not calendar-accurate accounting — "3mo ago" only needs to read as
// "between 2 and 4 months." Mixing two formats on the same page (the
// bug fixed in #487) was the actual readability problem; off-by-a-day
// rounding here is invisible by comparison.
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

/**
 * Format an ISO timestamp as a short, glanceable relative label.
 *
 * Returns "just now" / "Nm ago" / "Nh ago" / "Nd ago" / "Nmo ago" /
 * "Ny ago". One format across all magnitudes — never falls back to an
 * absolute date string (that mix is what made the Opps list confusing,
 * see issue #487). Callers that want the absolute timestamp on hover
 * should render it in a tooltip / `title` attribute themselves.
 */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const t = new Date(iso).getTime();
  const diff = Math.max(0, now - t);
  if (diff < MINUTE) return "just now";
  if (diff < HOUR) {
    const m = Math.floor(diff / MINUTE);
    return `${m}m ago`;
  }
  if (diff < DAY) {
    const h = Math.floor(diff / HOUR);
    return `${h}h ago`;
  }
  if (diff < MONTH) {
    const d = Math.floor(diff / DAY);
    return `${d}d ago`;
  }
  if (diff < YEAR) {
    const mo = Math.floor(diff / MONTH);
    return `${mo}mo ago`;
  }
  const y = Math.floor(diff / YEAR);
  return `${y}y ago`;
}
