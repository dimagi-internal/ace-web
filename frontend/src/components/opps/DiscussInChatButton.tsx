import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { discussStep } from "../../api/opps";

interface Props {
  slug: string;
  runId: string;
  skill: string;
}

export function DiscussInChatButton({ slug, runId, skill }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handle = async () => {
    setLoading(true);
    setError(null);
    try {
      const { session_slug } = await discussStep(slug, runId, skill);
      navigate(`/chat/${session_slug}`);
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
        className="rounded bg-gradient-to-br from-blue-500 to-violet-600 px-3 py-2.5 text-left text-xs font-semibold text-white shadow hover:from-blue-400 hover:to-violet-500 disabled:opacity-60"
      >
        <div className="text-[12px]">Discuss in chat</div>
        <div className="mt-0.5 text-[9px] font-normal text-blue-100">
          {loading
            ? "Creating session…"
            : "Opens a new ace-web session seeded with the IDD, this step's artifacts, and the judge verdict. Iterate on the output or push an updated SKILL.md from the chat."}
        </div>
      </button>
      {error && <div className="text-[10px] text-red-400">{error}</div>}
    </div>
  );
}
