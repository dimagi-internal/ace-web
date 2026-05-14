import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { MessageSquarePlus } from "lucide-react";

import { discussStep } from "../../api/opps";

interface Props {
  workspaceSlug: string;
  slug: string;
  runId: string;
  skill: string;
}

export function DiscussInChatButton({ workspaceSlug, slug, runId, skill }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handle = async () => {
    setLoading(true);
    setError(null);
    try {
      const { session_slug } = await discussStep(workspaceSlug, slug, runId, skill);
      navigate(`/w/${workspaceSlug}/chat/${session_slug}`);
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={handle}
        disabled={loading}
        className="flex items-center gap-2 rounded border border-border bg-card px-3 py-2 text-left text-xs text-foreground transition hover:border-primary/60 hover:bg-primary/10 disabled:opacity-60"
        title="Open a chat seeded with this step's artifacts so you can iterate on the output"
      >
        <MessageSquarePlus className="h-3.5 w-3.5 shrink-0 text-primary" />
        <div className="flex flex-col">
          <span className="font-semibold">
            {loading ? "Starting chat…" : "Discuss in chat"}
          </span>
          <span className="text-[10px] font-normal text-muted-foreground">
            Iterate on the output with ACE in a new session
          </span>
        </div>
      </button>
      {error && <div className="text-[10px] text-destructive">{error}</div>}
    </div>
  );
}
