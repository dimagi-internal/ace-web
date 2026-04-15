import { useState } from "react";

import { cliAuthSetToken } from "../api/auth";
import { useCliAuthStatus } from "../hooks/useCliAuthStatus";

type Phase = "idle" | "submitting" | "complete" | "error";

export function AuthCliPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const cliConnected = useCliAuthStatus(5000);

  const submit = async () => {
    setPhase("submitting");
    setError(null);
    try {
      await cliAuthSetToken(token.trim());
      setPhase("complete");
      setToken("");
    } catch (e) {
      setError(String(e));
      setPhase("error");
    }
  };

  return (
    <div className="mx-auto max-w-2xl p-6">
      <h1 className="mb-4 text-2xl font-semibold">Connect Claude CLI</h1>
      <p className="mb-4 text-muted-foreground">
        ace-web uses your team's Claude subscription via the local CLI. To
        authorize this server, generate an OAuth token on your laptop and
        paste it below.
      </p>

      {cliConnected === true && phase !== "complete" && (
        <div className="mb-4 rounded border border-green-300 bg-green-50 p-4 text-green-900">
          <div className="font-semibold">Claude CLI is connected</div>
          <p className="mt-1 text-sm">
            The server has a valid OAuth token. You can{" "}
            <a href="/chat" className="font-semibold underline">
              start chatting
            </a>
            , or paste a new token below to rotate.
          </p>
        </div>
      )}

      <div className="mb-4 rounded border border-border bg-muted p-4 text-sm">
        <div className="mb-2 font-semibold">How to get a token</div>
        <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
          <li>
            On your laptop, run:{" "}
            <code className="rounded bg-background px-1 py-0.5 font-mono">
              claude setup-token
            </code>
          </li>
          <li>Follow the browser prompts — the CLI will print a token starting with{" "}
            <code className="rounded bg-background px-1 py-0.5 font-mono">
              sk-ant-oat…
            </code>
          </li>
          <li>Copy that token and paste it below.</li>
        </ol>
      </div>

      <div className="space-y-3">
        <label htmlFor="token-input" className="block text-sm text-muted-foreground">
          OAuth token
        </label>
        <input
          id="token-input"
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="w-full rounded border border-border bg-background px-3 py-2 font-mono text-foreground"
          placeholder="sk-ant-oat01-…"
          autoComplete="off"
          spellCheck={false}
        />
        <button
          type="button"
          onClick={submit}
          disabled={!token.trim() || phase === "submitting"}
          className="rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50 hover:bg-primary/90"
        >
          {phase === "submitting" ? "Saving…" : "Save token"}
        </button>
      </div>

      {phase === "complete" && (
        <div className="mt-4 rounded border border-green-300 bg-green-50 p-4 text-green-900">
          Claude CLI is now connected. You can return to{" "}
          <a href="/chat" className="font-semibold underline">
            the chat page
          </a>
          .
        </div>
      )}

      {phase === "error" && (
        <div className="mt-4 rounded border border-red-300 bg-red-50 p-4 text-red-900">
          <div className="font-semibold">Could not save token</div>
          <div className="text-sm">{error}</div>
        </div>
      )}
    </div>
  );
}
