import { Link } from "react-router-dom";

import { useCliAuthStatus } from "../hooks/useCliAuthStatus";

/**
 * Claude CLI connection status + instructions for connecting.
 *
 * The server does not run ``claude setup-token`` itself anymore — too
 * fragile on headless Linux (PTY cursor positioning, line wrap, ANSI
 * escapes eating token chars). Developers run ``ace_cli_login`` on
 * their laptop to upload the local credential blob.
 */
function serverBaseUrl(): string {
  if (typeof window === "undefined") return "<ace-url>";
  const base = import.meta.env.BASE_URL || "/";
  const trimmed = base.endsWith("/") ? base.slice(0, -1) : base;
  return window.location.origin + trimmed;
}

export function AuthCliPage() {
  const cliConnected = useCliAuthStatus(5000);
  const baseUrl = serverBaseUrl();

  return (
    <div className="mx-auto max-w-2xl p-6">
      <h1 className="mb-4 text-2xl font-semibold">Connect Claude CLI</h1>
      <p className="mb-4 text-muted-foreground">
        ace-web drives chat through the <code className="rounded bg-muted px-1">claude</code>{" "}
        CLI, authenticated with your team's Claude subscription. To share your
        local CLI credentials with this server, run the helper script from
        your laptop.
      </p>

      {cliConnected === true ? (
        <div className="rounded border border-green-300 bg-green-50 p-4 text-green-900">
          <div className="font-semibold">Claude CLI is connected</div>
          <p className="mt-1 text-sm">
            The server has a valid credential blob and a live check against
            Anthropic just passed. You can{" "}
            <Link to="/chat" className="font-semibold underline">
              start chatting
            </Link>
            .
          </p>
        </div>
      ) : cliConnected === false ? (
        <div className="rounded border border-amber-300 bg-amber-50 p-4 text-amber-900">
          <div className="font-semibold">Not connected</div>
          <p className="mt-1 text-sm">
            The server has no credentials, or the stored token failed a live
            check (expired or revoked).
          </p>
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">Checking CLI status…</div>
      )}

      <div className="mt-6 space-y-3">
        <h2 className="text-lg font-semibold">How to connect</h2>
        <ol className="list-decimal space-y-2 pl-5 text-sm">
          <li>
            Authenticate the claude CLI locally (once):{" "}
            <code className="rounded bg-muted px-1">claude setup-token</code>{" "}
            and complete the browser flow. Skip this if you already use{" "}
            <code className="rounded bg-muted px-1">claude -p</code> locally.
          </li>
          <li>
            Mint a personal access token at{" "}
            <Link to="/settings" className="font-semibold underline">
              /settings
            </Link>
            .
          </li>
          <li>
            From the ace-web checkout, run:
            <pre className="mt-1 overflow-x-auto rounded bg-muted p-3 text-xs">
              <code>
                {`ACE_URL=${baseUrl} ACE_TOKEN=<token> python scripts/ace_cli_login.py`}
              </code>
            </pre>
          </li>
          <li>
            The script reads your local credential blob (macOS Keychain or{" "}
            <code className="rounded bg-muted px-1">~/.claude/.credentials.json</code>)
            and POSTs it to this server. Refresh this page when done.
          </li>
        </ol>
        <p className="text-xs text-muted-foreground">
          The credential blob includes a refresh token, so the server's{" "}
          <code className="rounded bg-muted px-1">claude</code> CLI keeps
          working as tokens rotate — no re-upload needed unless you revoke.
        </p>
      </div>
    </div>
  );
}
