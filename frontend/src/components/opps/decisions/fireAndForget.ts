/**
 * Swallow a rejection from a fire-and-forget handler.
 *
 * The decision surfaces render a failed save through their own `error`
 * state, so the promise itself has nowhere to go. Without this, every
 * failed save ALSO lands as an unhandled promise rejection — which CI
 * fails on, and which a partner would see in their console.
 */
export function fireAndForget(result: unknown): void {
  if (result instanceof Promise) result.catch(() => undefined);
}
