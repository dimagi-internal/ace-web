import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { createSession } from "../api/sessions";

export function ChatRedirectPage() {
  const navigate = useNavigate();
  const { workspaceSlug = "" } = useParams<{ workspaceSlug?: string }>();

  useEffect(() => {
    if (!workspaceSlug) return;
    createSession(workspaceSlug).then((s) => {
      navigate(`/w/${workspaceSlug}/chat/${s.slug}`, { replace: true });
    });
  }, [navigate, workspaceSlug]);

  return <div className="p-4 text-muted-foreground">Starting a new chat…</div>;
}
