export function formatUsd(value: number, partial = false): string {
  const fixed = value < 0.01 && value > 0 ? value.toFixed(4) : value.toFixed(2);
  return partial ? `~$${fixed}*` : `$${fixed}`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return s ? `${m}m ${s}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return mm ? `${h}h ${mm}m` : `${h}h`;
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function formatCacheHitRatio(ratio: number): string {
  return `${Math.round(ratio * 100)}%`;
}

export interface CostTokenBreakdown {
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
}

/** Sum across input + output + cache_creation + cache_read. */
export function totalTokens(t: CostTokenBreakdown): number {
  return (
    t.input_tokens + t.output_tokens + t.cache_creation_tokens + t.cache_read_tokens
  );
}
