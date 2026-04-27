import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import {
  createWorkspace,
  getDriveConfig,
  verifyDriveAccess,
  type VerifyResult,
} from "../api/workspaces";
import { Button } from "@/components/ui/button";

type Step = "name" | "folder" | "verifying" | "verified" | "creating";

export default function WelcomePage() {
  const [params] = useSearchParams();
  const inviteToken = params.get("invite");
  const navigate = useNavigate();

  // If there's an invite param, redirect to the accept page.
  useEffect(() => {
    if (inviteToken) navigate(`/invite/${inviteToken}`, { replace: true });
  }, [inviteToken, navigate]);

  const [step, setStep] = useState<Step>("name");
  const [displayName, setDisplayName] = useState("");
  const [folderInput, setFolderInput] = useState("");
  const [createdSlug, setCreatedSlug] = useState<string | null>(null);
  const [saEmail, setSaEmail] = useState<string>("");
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <div className="mx-auto max-w-2xl px-6 py-12">
      <h1 className="text-3xl font-semibold text-foreground">Welcome to ACE</h1>
      <p className="mt-2 text-muted-foreground">
        Create a workspace to get started, or paste an invite link.
      </p>

      <div className="mt-8 rounded border border-border bg-card p-6">
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
            <p className="mt-1 text-xs text-muted-foreground">
              ACE reads and writes opp artifacts in this folder. Share it with
              the service account as <strong>Editor</strong> first:
            </p>
            <pre className="mt-2 select-all rounded bg-muted px-3 py-2 text-sm font-mono text-foreground">
              {saEmail || "(loading service-account email…)"}
            </pre>
            <p className="mt-3 text-xs text-muted-foreground">
              Then paste the folder ID or URL here:
            </p>
            <input
              type="text"
              value={folderInput}
              onChange={(e) => setFolderInput(e.target.value)}
              placeholder="folder ID or https://drive.google.com/drive/folders/…"
              className="mt-2 w-full rounded border border-input bg-background px-3 py-2 text-sm text-foreground"
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
                <p className="mt-3 text-xs text-muted-foreground">
                  Double-check the folder is shared with{" "}
                  <span className="font-mono">{saEmail}</span> as Editor.
                </p>
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
