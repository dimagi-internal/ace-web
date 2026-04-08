import { useState } from "react";

import {
  cliAuthCancel,
  cliAuthComplete,
  cliAuthStart,
  cliAuthStatus,
} from "../api/auth";

type Phase = "idle" | "awaiting_code" | "submitting" | "complete" | "error";

export function AuthCliPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setError(null);
    setPhase("idle");
    try {
      const r = await cliAuthStart();
      if (r.status === "complete") {
        setPhase("complete");
      } else {
        setPhase("awaiting_code");
        setAuthUrl(r.auth_url);
      }
    } catch (e) {
      setError(String(e));
      setPhase("error");
    }
  };

  const submit = async () => {
    setPhase("submitting");
    setError(null);
    try {
      await cliAuthComplete(code);
      setPhase("complete");
      await cliAuthStatus();
    } catch (e) {
      setError(String(e));
      setPhase("error");
    }
  };

  const cancel = async () => {
    await cliAuthCancel();
    setPhase("idle");
    setAuthUrl(null);
    setCode("");
  };

  return (
    <div className="mx-auto max-w-2xl p-6">
      <h1 className="mb-4 text-2xl font-semibold">Connect Claude CLI</h1>
      <p className="mb-4 text-zinc-600">
        ace-web uses your team's Claude subscription via the local CLI. To
        authorize this server, generate an OAuth token using the flow below.
      </p>

      {phase === "idle" && (
        <button
          type="button"
          onClick={start}
          className="rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700"
        >
          Begin authorization
        </button>
      )}

      {phase === "awaiting_code" && authUrl && (
        <div className="space-y-4">
          <div className="rounded border border-zinc-200 bg-zinc-50 p-4">
            <p className="mb-2 text-sm text-zinc-700">
              1. Open this URL in a browser logged into your Claude account:
            </p>
            <a
              href={authUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all font-mono text-sm text-blue-600 underline"
            >
              {authUrl}
            </a>
          </div>
          <div>
            <p className="mb-2 text-sm text-zinc-700">
              2. Paste the resulting code here:
            </p>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="w-full rounded border border-zinc-300 px-3 py-2 font-mono"
              placeholder="paste-code-here"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={!code.trim()}
              className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50 hover:bg-blue-700"
            >
              Submit code
            </button>
            <button
              type="button"
              onClick={cancel}
              className="rounded border border-zinc-300 px-4 py-2 text-zinc-700 hover:bg-zinc-100"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {phase === "submitting" && (
        <div className="text-zinc-500">Submitting code…</div>
      )}

      {phase === "complete" && (
        <div className="rounded border border-green-300 bg-green-50 p-4 text-green-900">
          Claude CLI is now connected. You can return to{" "}
          <a href="/chat" className="font-semibold underline">
            the chat page
          </a>
          .
        </div>
      )}

      {phase === "error" && (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-red-900">
          <div className="font-semibold">Authorization failed</div>
          <div className="text-sm">{error}</div>
          <button
            type="button"
            onClick={() => setPhase("idle")}
            className="mt-2 rounded border border-red-300 px-3 py-1 text-sm hover:bg-red-100"
          >
            Try again
          </button>
        </div>
      )}
    </div>
  );
}
