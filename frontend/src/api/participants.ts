import { apiFetch } from "./client";
import type { Participant } from "./types.ws";

/**
 * participants.ts — session participants API client.
 *
 * POST /api/sessions/{slug}/participants is a legacy DRF endpoint not yet
 * in v2. Import `Participant` from types.ws instead of the deleted types.ts.
 */
export const addParticipant = (slug: string, email: string): Promise<Participant> =>
  apiFetch<Participant>(`/api/sessions/${slug}/participants`, {
    method: "POST",
    body: JSON.stringify({ email }),
  });
