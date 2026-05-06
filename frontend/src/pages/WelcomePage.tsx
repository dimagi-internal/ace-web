import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, Check, Copy } from "lucide-react";
import { toast } from "sonner";

import {
  createWorkspace,
  getDriveConfig,
  verifyDriveAccess,
  type VerifyResult,
} from "../api/workspaces";
import { Button } from "@/components/ui/button";
import { useWorkspace } from "../hooks/useWorkspace";

type Step = "name" | "folder" | "verifying" | "verified" | "creating";

export default function WelcomePage() {
  const [params] = useSearchParams();
  const inviteToken = params.get("invite");
  const navigate = useNavigate();
  const { all: existingWorkspaces, loading: workspacesLoading } = useWorkspace();

  // If there's an invite param, redirect to the accept page.
  useEffect(() => {
    if (inviteToken) navigate(`/invite/${inviteToken}`, { replace: true });
  }, [inviteToken, navigate]);

  const [step, setStep] = useState<Step>("name");
  const [displayName, setDisplayName] = useState("");
  const [folderInput, setFolderInput] = useState("");
  const [createdSlug, setCreatedSlug] = useState<string | null>(null);
  const [saEmail, setSaEmail] = useState<string>("");
  const [saCopied, setSaCopied] = useState(false);
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function copySaEmail() {
    if (!saEmail) return;
    try {
      await navigator.clipboard.writeText(saEmail);
      setSaCopied(true);
      toast.success("Service-account email copied");
      setTimeout(() => setSaCopied(false), 1500);
    } catch {
      toast.error("Couldn't copy — select and copy manually");
    }
  }

  // Fetch SA email up-front so we can show "share this folder with X".
  useEffect(() => {
    getDriveConfig()
      .then((c) => setSaEmail(c.service_account_email))
      .catch(() => setSaEmail(""));
  }, []);

  async function handleCreate() {
    setStep("creating");
    setError(null);
    try {
      const ws = await createWorkspace({
        display_name: displayName.trim(),
        drive_root_folder_id: folderInput.trim(),
      });
      setCreatedSlug(ws.slug);
      // Now verify Drive access for the newly-created workspace.
      setStep("verifying");
      try {
        const result = await verifyDriveAccess(ws.slug);
        setVerifyResult(result);
        setStep("verified");
      } catch (e) {
        setError(String((e as Error).message));
        setStep("verifying");
      }
    } catch (e) {
      setError(String((e as Error).message));
      setStep("folder");
    }
  }

  if (inviteToken) return null;

  const hasExisting = !workspacesLoading && existingWorkspaces.length > 0;

  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <h1 className="text-3xl font-semibold text-foreground">Welcome to ACE</h1>
      <p className="mt-2 text-muted-foreground">
        {hasExisting
          ? "Pick a workspace below, or create another one."
          : "Create a workspace to get started, or paste an invite link."}
      </p>

      {hasExisting && (
        <div className="mt-8 rounded border border-border bg-card p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Your workspaces
          </h2>
          <ul className="mt-3 divide-y divide-border">
            {existingWorkspaces.map((ws) => (
              <li key={ws.slug}>
                <button
                  type="button"
                  onClick={() => navigate(`/w/${ws.slug}/opps`)}
                  className="group flex w-full items-center justify-between gap-3 rounded px-2 py-3 text-left hover:bg-accent"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-foreground">
                      {ws.display_name}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {ws.slug}
                      {ws.role && <> · {ws.role}</>}
                    </p>
                  </div>
                  <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground group-hover:text-foreground" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-6 rounded border border-border bg-card p-6">
        {hasExisting && step === "name" && (
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Create another workspace
          </h2>
        )}
        {step === "name" && (
          <>
            <label className="block text-sm font-medium text-foreground">
              Workspace name
            </label>
            <p className="mt-1 text-xs text-muted-foreground">
              Pick something your team will recognize — e.g. "Acme Health Programs".
            </p>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Acme Health Programs"
              className="mt-3 w-full rounded border border-input bg-background px-3 py-2 text-sm text-foreground"
              autoFocus
            />
            <div className="mt-4 flex justify-end">
              <Button
                onClick={() => setStep("folder")}
                disabled={!displayName.trim()}
              >
                Next
              </Button>
            </div>
          </>
        )}

        {step === "folder" && (
          <>
            <label className="block text-sm font-medium text-foreground">
              Connect your Google Drive folder
            </label>
            <ol className="mt-3 space-y-3 text-xs text-muted-foreground">
              <li>
                <span className="font-semibold text-foreground">1.</span> Create
                (or pick) a folder in your Google Drive that ACE can read and
                write. Empty is fine.
              </li>
              <li>
                <span className="font-semibold text-foreground">2.</span> Share
                it with this service-account email as <strong>Editor</strong>:
                <button
                  type="button"
                  onClick={copySaEmail}
                  disabled={!saEmail}
                  className="mt-1 flex w-full items-center justify-between gap-2 rounded bg-muted px-3 py-2 text-left font-mono text-sm text-foreground hover:bg-muted/70 disabled:opacity-60"
                  title="Click to copy"
                >
                  <span className="select-all">
                    {saEmail || "(loading service-account email…)"}
                  </span>
                  {saCopied ? (
                    <Check className="h-4 w-4 shrink-0 text-green-500" />
                  ) : (
                    <Copy className="h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                </button>
              </li>
              <li>
                <span className="font-semibold text-foreground">3.</span> Paste
                the folder URL or ID below. The URL looks like{" "}
                <span className="font-mono text-foreground">
                  drive.google.com/drive/folders/<span className="bg-primary/10 px-0.5">1AbCxYz…</span>
                </span>{" "}
                — the highlighted part is the ID.
              </li>
            </ol>
            <input
              type="text"
              value={folderInput}
              onChange={(e) => setFolderInput(e.target.value)}
              placeholder="folder ID or https://drive.google.com/drive/folders/…"
              className="mt-3 w-full rounded border border-input bg-background px-3 py-2 text-sm text-foreground"
            />
            {error && (
              <p className="mt-2 text-sm text-destructive">{error}</p>
            )}
            <div className="mt-4 flex justify-between">
              <Button variant="ghost" onClick={() => setStep("name")}>
                Back
              </Button>
              <Button
                onClick={handleCreate}
                disabled={!folderInput.trim() || !displayName.trim()}
              >
                Create workspace
              </Button>
            </div>
          </>
        )}

        {step === "creating" && (
          <p className="text-sm text-muted-foreground">Creating workspace…</p>
        )}

        {step === "verifying" && (
          <>
            <p className="text-sm text-muted-foreground">
              Workspace created. Verifying Drive access…
            </p>
            {error && (
              <>
                <p className="mt-2 text-sm text-destructive">{error}</p>
                <div className="mt-3 rounded border border-border bg-muted/50 p-3 text-xs text-muted-foreground">
                  <p className="font-medium text-foreground">
                    Most likely fix:
                  </p>
                  <ol className="mt-1 list-decimal space-y-1 pl-4">
                    <li>
                      Open the folder in Google Drive and share it with{" "}
                      <button
                        type="button"
                        onClick={copySaEmail}
                        disabled={!saEmail}
                        className="inline-flex items-center gap-1 rounded bg-card px-1.5 py-0.5 font-mono text-foreground hover:bg-card/70 disabled:opacity-60"
                        title="Click to copy"
                      >
                        {saEmail}
                        {saCopied ? (
                          <Check className="h-3 w-3 text-green-500" />
                        ) : (
                          <Copy className="h-3 w-3" />
                        )}
                      </button>{" "}
                      as <strong>Editor</strong>.
                    </li>
                    <li>Wait a few seconds for the share to propagate.</li>
                    <li>Click <strong>Retry verification</strong> below.</li>
                  </ol>
                </div>
                <div className="mt-3 flex gap-2">
                  <Button
                    variant="outline"
                    onClick={async () => {
                      if (!createdSlug) return;
                      setError(null);
                      try {
                        const r = await verifyDriveAccess(createdSlug);
                        setVerifyResult(r);
                        setStep("verified");
                      } catch (e) {
                        setError(String((e as Error).message));
                      }
                    }}
                  >
                    Retry verification
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => navigate(`/w/${createdSlug}/opps`)}
                  >
                    Skip for now
                  </Button>
                </div>
              </>
            )}
          </>
        )}

        {step === "verified" && verifyResult && createdSlug && (
          <>
            <p className="text-sm text-foreground">
              Workspace created and Drive access verified.
              {verifyResult.total_visible > 0 && (
                <> Saw {verifyResult.total_visible} files at the root.</>
              )}
            </p>
            {verifyResult.sample_files.length > 0 && (
              <ul className="mt-2 list-disc pl-5 text-xs text-muted-foreground">
                {verifyResult.sample_files.map((f) => (
                  <li key={f.name}>{f.name}</li>
                ))}
              </ul>
            )}
            <div className="mt-4 flex justify-end">
              <Button onClick={() => navigate(`/w/${createdSlug}/opps`)}>
                Go to workspace
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
