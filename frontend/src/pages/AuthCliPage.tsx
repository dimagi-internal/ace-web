import { useState } from "react";
import { Link } from "react-router-dom";

import {
  cliAuthCancel,
  cliAuthComplete,
  cliAuthStart,
  cliAuthStatus,
} from "../api/auth";
import { useCliAuthStatus } from "../hooks/useCliAuthStatus";

type Phase = "idle" | "starting" | "awaiting_code" | "submitting" | "complete" | "error";

export function AuthCliPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const cliConnected = useCliAuthStatus(5000);

  const start = async () => {
    setError(null);
    setPhase("starting");
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
            The server has a valid CLI OAuth token. You can{" "}
            <Link to="/chat" className="font-semibold underline">
              start chatting
            </Link>
            .
          </p>
        </div>
      )}

      {cliConnected === false && phase === "idle" && (
        <div className="space-y-4">
          <div className="rounded border border-amber-300 bg-amber-50 p-4 text-amber-900">
            <div className="font-semibold">CLI token not set</div>
            <div className="mt-1 text-sm">
              The server needs a Claude CLI OAuth token to use your team's
              subscription. Click below to authorize.
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
        <div className="text-sm text-muted-foreground">Checking CLI status…</div>
      )}

      {phase === "starting" && (
        <div className="flex items-center gap-2 text-muted-foreground">
          <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Starting authorization…
        </div>
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
        <div className="flex items-center gap-2 text-muted-foreground">
          <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Exchanging code for token (up to 90 s)…
        </div>
      )}

      {phase === "complete" && (
        <div className="rounded border border-green-300 bg-green-50 p-4 text-green-900">
          Claude CLI is now connected. You can return to{" "}
          <Link to="/chat" className="font-semibold underline">
            the chat page
          </Link>
          .
        </div>
      )}

      {phase === "error" && (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-red-900">
          <div className="font-semibold">Authorization failed</div>
          <div className="text-sm">{error}</div>
          <button
            type="button"
            onClick={start}
            className="mt-2 rounded border border-red-300 px-3 py-1 text-sm hover:bg-red-100"
          >
            Try again
          </button>
        </div>
      )}
    </div>
  );
}
