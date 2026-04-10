import type { ApiEnvelope } from "./types";

interface UploadResult {
  session_slug: string;
  message_count: number;
  cli_session_id: string;
}

const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");

function getCsrfToken(): string {
  const cookies = document.cookie.split(";");
  for (const raw of cookies) {
    const [rawName, ...rawValue] = raw.trim().split("=");
    if (rawName === "csrftoken_ace" || rawName === "csrftoken") {
      return decodeURIComponent(rawValue.join("="));
    }
  }
  return "";
}

export const uploadSession = async (file: File): Promise<UploadResult> => {
  const formData = new FormData();
  formData.append("file", file);
  const resp = await fetch(`${API_PREFIX}/api/ingest/upload`, {
    method: "POST",
    body: formData,
    credentials: "same-origin",
    headers: { "X-CSRFToken": getCsrfToken() },
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
