import { apiFetch } from "./client";
import type { Participant } from "./types";

export const addParticipant = (slug: string, email: string) =>
  apiFetch<Participant>(`/api/sessions/${slug}/participants`, {
    method: "POST",
    body: JSON.stringify({ email }),
  });
