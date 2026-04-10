import type { ApiEnvelope } from "./types";

interface UploadResult {
  session_slug: string;
  message_count: number;
  cli_session_id: string;
}

const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");

export const uploadSession = async (file: File): Promise<UploadResult> => {
  const formData = new FormData();
  formData.append("file", file);
  const resp = await fetch(`${API_PREFIX}/api/ingest/upload`, {
    method: "POST",
    body: formData,
    credentials: "same-origin",
  });
  const json: ApiEnvelope<UploadResult> = await resp.json();
  if (json.error) {
    throw new Error(json.error.message);
  }
  if (!json.data) {
    throw new Error("No data in response");
  }
  return json.data;
};
