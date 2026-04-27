import { ChevronDown } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useWorkspace } from "../hooks/useWorkspace";

export function WorkspaceSwitcher() {
  const { current, all, loading } = useWorkspace();
  const navigate = useNavigate();

  if (loading) return null;

  if (all.length === 0) {
    return (
      <button
        type="button"
        onClick={() => navigate("/welcome")}
        className="rounded border border-dashed border-input px-3 py-1.5 text-sm text-muted-foreground hover:border-input/80"
      >
        Set up a workspace
      </button>
    );
  }

  return (
    <div className="relative inline-block">
      <select
        className="appearance-none rounded border border-input bg-card px-3 py-1.5 pr-8 text-sm font-medium text-foreground"
        value={current?.slug ?? ""}
        onChange={(e) => {
          const target = e.target.value;
          if (target) navigate(`/w/${target}/opps`);
        }}
      >
        <option value="" disabled>
          {current ? current.display_name : "Pick a workspace"}
        </option>
        {all.map((w) => (
          <option key={w.slug} value={w.slug}>
            {w.display_name}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}
