import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getSharedSession } from "../api/share";
import { ApiError } from "../api/client";
import { MessageItem } from "../components/MessageItem";
import type { SharedSession } from "../api/types.ws";

type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; session: SharedSession }
  | { kind: "error"; code: string; message: string };

export default function ShareViewPage() {
  const { token = "" } = useParams();
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    if (!token) return;
    getSharedSession(token)
      .then((session) => setState({ kind: "loaded", session }))
      .catch((e) => {
        if (e instanceof ApiError) {
          setState({ kind: "error", code: e.code, message: e.message });
        } else {
          setState({ kind: "error", code: "unknown", message: "Failed to load" });
        }
      });
  }, [token]);

  if (state.kind === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-zinc-500">Loading shared session...</p>
      </div>
    );
  }

  if (state.kind === "error") {
    const message =
      state.code === "revoked"
        ? "This share link has been revoked."
        : state.code === "not_found"
          ? "This share link is invalid or has expired."
          : state.message;
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <p className="text-lg font-medium text-zinc-700">{message}</p>
        </div>
      </div>
    );
  }

  const { session } = state;

  return (
    <div className="mx-auto max-w-3xl py-6">
      <div className="mb-4 rounded-md border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-700">
        Shared session — read only
      </div>
      <h1 className="mb-4 text-xl font-semibold text-zinc-800">
        {session.title || "Untitled session"}
      </h1>
      <div className="space-y-1">
        {session.messages.map((msg) => (
          <MessageItem
            key={msg.turn_index}
            message={{
              ...msg,
              id: msg.turn_index,
              error_detail: null,
              started_at: null,
              completed_at: null,
            }}
          />
        ))}
      </div>
    </div>
  );
}
