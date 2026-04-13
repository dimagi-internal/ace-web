import { useState } from "react";

import {
  cliAuthCancel,
  cliAuthComplete,
  cliAuthStart,
  cliAuthStatus,
} from "../api/auth";
import { useCliAuthStatus } from "../hooks/useCliAuthStatus";

type Phase = "idle" | "awaiting_code" | "submitting" | "complete" | "error";

export function AuthCliPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const cliConnected = useCliAuthStatus(5000);

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
      const msg = String(e);
      // Server-side PTY died (deploy restart, timeout). Auto-restart
      // instead of making the user click "Try again" + "Begin authorization".
      if (msg.includes("No active auth flow") || msg.includes("start() first")) {
        setPhase("idle");
        setAuthUrl(null);
        setCode("");
        return;
      }
      setError(msg);
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
      <p className="mb-4 text-muted-foreground">
        ace-web uses your team's Claude subscription via the local CLI. To
        authorize this server, generate an OAuth token using the flow below.
      </p>

      {cliConnected === true && phase === "idle" && (
        <div className="rounded border border-green-300 bg-green-50 p-4 text-green-900">
          <div className="font-semibold">Claude CLI is connected</div>
          <p className="mt-1 text-sm">
            The server has a valid OAuth token. You can{" "}
            <a href="/chat" className="font-semibold underline">
              start chatting
            </a>
            , or re-authorize below if the token needs refreshing.
          </p>
          <button
            type="button"
            onClick={start}
            className="mt-3 rounded border border-green-300 px-4 py-2 text-sm text-green-900 hover:bg-green-100"
          >
            Re-authorize
          </button>
        </div>
      )}

      {cliConnected === false && phase === "idle" && (
        <div className="space-y-4">
          <div className="rounded border border-border bg-muted p-4">
            <div className="text-sm text-muted-foreground">
              Logged in. CLI token is not set on this server.
            </div>
          </div>
          <button
            type="button"
            onClick={start}
            className="rounded bg-primary px-4 py-2 text-primary-foreground hover:bg-primary/90"
          >
            Begin authorization
          </button>
        </div>
      )}

      {cliConnected === null && phase === "idle" && (
        <div className="text-sm text-muted-foreground">Checking CLI status...</div>
      )}

      {phase === "awaiting_code" && authUrl && (
        <div className="space-y-4">
          <div className="rounded border border-border bg-muted p-4">
            <p className="mb-2 text-sm text-muted-foreground">
              1. Open this URL in a browser logged into your Claude account:
            </p>
            <a
              href={authUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all font-mono text-sm text-primary underline"
            >
              {authUrl}
            </a>
          </div>
          <div>
            <p className="mb-2 text-sm text-muted-foreground">
              2. Paste the resulting code here:
            </p>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="w-full rounded border border-border bg-background px-3 py-2 font-mono text-foreground"
              placeholder="paste-code-here"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={!code.trim()}
              className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50 hover:bg-primary/90"
            >
              Submit code
            </button>
            <button
              type="button"
              onClick={cancel}
              className="rounded border border-border px-4 py-2 text-muted-foreground hover:bg-accent"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {phase === "submitting" && (
        <div className="text-muted-foreground">Submitting code…</div>
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
