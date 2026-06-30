import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  acceptInvite,
  getInvitePreview,
  type InvitePreview,
} from "../api/workspaces";
import { Button } from "canopy-ui/ui";

export default function InviteAcceptPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    if (!token) return;
    getInvitePreview(token)
      .then(setPreview)
      .catch((e) => setError(String((e as Error).message)));
  }, [token]);

  async function handleAccept() {
    if (!token) return;
    setAccepting(true);
    setError(null);
    try {
      const result = await acceptInvite(token);
      navigate(`/w/${result.workspace_slug}/opps`, { replace: true });
    } catch (e) {
      setError(String((e as Error).message));
      setAccepting(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl px-6 py-12">
      <h1 className="text-2xl font-semibold text-foreground">
        Workspace invitation
      </h1>
      <div className="mt-6 rounded border border-border bg-card p-6">
        {error && <p className="text-sm text-destructive">{error}</p>}
        {!preview && !error && (
          <p className="text-sm text-muted-foreground">Loading invitation…</p>
        )}
        {preview && (
          <>
            <p className="text-sm text-muted-foreground">
              You've been invited to join
            </p>
            <p className="mt-1 text-xl font-semibold text-foreground">
              {preview.workspace_display_name}
            </p>
            <dl className="mt-4 grid grid-cols-[120px_1fr] gap-y-2 text-sm">
              <dt className="text-muted-foreground">Role:</dt>
              <dd className="text-foreground">{preview.role}</dd>
              <dt className="text-muted-foreground">Invited by:</dt>
              <dd className="text-foreground">{preview.invited_by_email}</dd>
              <dt className="text-muted-foreground">Sent to:</dt>
              <dd className="text-foreground">{preview.email}</dd>
            </dl>
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => navigate("/welcome")}>
                Decline
              </Button>
              <Button onClick={handleAccept} disabled={accepting}>
                {accepting ? "Accepting…" : "Accept invitation"}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
