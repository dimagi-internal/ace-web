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

  // Keep a tiny "Workspace" label outside the switcher so the bare
  // workspace name doesn't read as a passive header — new users
  // wouldn't otherwise realize they can switch context here.
  const switcherTitle =
    all.length > 1
      ? `Switch workspace (${all.length} available)`
      : current?.display_name
        ? `Workspace: ${current.display_name}`
        : "Workspace";
  return (
    <div className="flex items-center gap-1.5">
      <span className="hidden text-[10px] uppercase tracking-wider text-muted-foreground sm:inline">
        Workspace
      </span>
      <div className="relative inline-block">
        <select
          className="appearance-none rounded border border-input bg-card px-3 py-1.5 pr-8 text-sm font-medium text-foreground hover:border-primary/60"
          value={current?.slug ?? ""}
          onChange={(e) => {
            const target = e.target.value;
            if (target) navigate(`/w/${target}/opps`);
          }}
          aria-label={switcherTitle}
          title={switcherTitle}
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
    </div>
  );
}
