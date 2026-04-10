import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { createSession } from "../api/sessions";

export function ChatRedirectPage() {
  const navigate = useNavigate();

  useEffect(() => {
    createSession().then((s) => {
      navigate(`/chat/${s.slug}`, { replace: true });
    });
  }, [navigate]);

  return <div className="p-4 text-muted-foreground">Starting a new chat…</div>;
}
