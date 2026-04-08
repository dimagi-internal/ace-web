import { apiFetch } from "./client";

export interface SendMessageResult {
  user_message_id: number;
  assistant_message_id: number;
}

export const sendMessage = (slug: string, text: string) =>
  apiFetch<SendMessageResult>(`/api/sessions/${slug}/messages`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });

export const streamUrl = (assistantMessageId: number) =>
  `/api/messages/${assistantMessageId}/stream`;
