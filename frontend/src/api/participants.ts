import type { Participant } from "./types.ws";

/**
 * participants.ts — session participants API client.
 *
 * POST /api/sessions/{slug}/participants was a legacy DRF endpoint.
 * There is no v2 POST participants endpoint — only GET /participants exists in v2.
 * Callers will fail loudly until the backend ships a v2 add-participant endpoint.
 */
export const addParticipant = (_slug: string, _email: string): Promise<Participant> =>
  Promise.reject(
    new Error(
      "addParticipant: POST participants endpoint not available in v2 — " +
        "will be addressed in a future PR",
    ),
  );
