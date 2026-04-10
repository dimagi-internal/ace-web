import { apiFetch } from "./client";
import type { Message } from "./types";

export const listMessages = (slug: string) =>
  apiFetch<Message[]>(`/api/sessions/${slug}/messages`);
