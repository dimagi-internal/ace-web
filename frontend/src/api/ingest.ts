import type { components } from "./generated";

type IngestUploadOut = components["schemas"]["IngestUploadOut"];

interface UploadResult {
  session_slug: string;
  message_count: number;
  cli_session_id: string;
}

function getCsrfToken(): string {
  if (typeof document === "undefined") return "";
  const cookies = document.cookie.split(";");
  for (const raw of cookies) {
    const [rawName, ...rawValue] = raw.trim().split("=");
    if (rawName === "csrftoken_ace" || rawName === "csrftoken") {
      return decodeURIComponent(rawValue.join("="));
    }
  }
  return "";
}

/**
 * Upload a JSONL session transcript via the v2 ingest endpoint.
 *
 * The v2 endpoint accepts multipart/form-data and returns `IngestUploadOut`.
 * openapi-fetch doesn't handle FormData bodies well (the generated schema
 * types the body as a plain object), so we use a raw fetch with the v2 URL
 * while reusing the CSRF helper from the middleware pattern.
 */
export const uploadSession = async (
  file: File,
  workspaceSlug?: string,
): Promise<UploadResult> => {
  const API_PREFIX = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  const formData = new FormData();
  formData.append("file", file);
  if (workspaceSlug) {
    formData.append("workspace_slug", workspaceSlug);
  }
  const resp = await fetch(`${API_PREFIX}/api/ingest/upload`, {
    method: "POST",
    body: formData,
    credentials: "same-origin",
    headers: {
      "X-Requested-With": "XMLHttpRequest",
      "X-CSRFToken": getCsrfToken(),
    },
  });

  if (!resp.ok) {
    const text = await resp.text().catch(() => resp.statusText);
    throw new Error(`Upload failed (${resp.status}): ${text}`);
  }

  const json = (await resp.json()) as IngestUploadOut;
  return {
    session_slug: json.session_slug,
    message_count: json.messages_imported,
    cli_session_id: json.cli_session_id ?? "",
  };
};
