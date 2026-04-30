import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";
import { EmptyState } from "../opps/LoadingStates";
import type { McpServerSummary, McpToolSummary, SystemSnapshot } from "./types";

interface Props {
  snapshot: SystemSnapshot;
}

export function McpsView({ snapshot }: Props) {
  const [selected, setSelected] = useState<string | null>(snapshot.mcps[0]?.name ?? null);
  const [filter, setFilter] = useState("");

  const selectedServer = useMemo(
    () => snapshot.mcps.find((s) => s.name === selected) ?? null,
    [snapshot.mcps, selected],
  );

  if (snapshot.mcps.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <EmptyState
          title="No MCP servers"
          description="The ACE plugin's plugin.json doesn't declare any mcpServers."
        />
      </div>
    );
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      <aside className="w-[220px] shrink-0 overflow-y-auto border-r border-border">
        <McpSidebar servers={snapshot.mcps} selected={selected} onSelect={setSelected} />
      </aside>
      <main className="flex-1 overflow-y-auto">
        {selectedServer ? (
          <McpServerPane server={selectedServer} filter={filter} onFilterChange={setFilter} />
        ) : (
          <div className="flex h-full items-center justify-center">
            <EmptyState title="Select an MCP server" description="Choose a server to see its tools." />
          </div>
        )}
      </main>
    </div>
  );
}

interface SidebarProps {
  servers: McpServerSummary[];
  selected: string | null;
  onSelect: (name: string) => void;
}

function McpSidebar({ servers, selected, onSelect }: SidebarProps) {
  return (
    <nav className="flex flex-col py-2">
      <div className="px-4 pb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        MCP Servers
      </div>
      {servers.map((s) => {
        const isSelected = s.name === selected;
        return (
          <button
            key={s.name}
            type="button"
            onClick={() => onSelect(s.name)}
            className={cn(
              "flex flex-col items-start px-4 py-2 text-left text-xs hover:bg-accent",
              isSelected && "bg-accent",
            )}
          >
            <span className={cn("font-mono text-sm", isSelected ? "text-foreground" : "text-foreground/90")}>
              {s.name}
            </span>
            <span className="text-muted-foreground">
              {s.tools.length} {s.tools.length === 1 ? "tool" : "tools"}
              {s.warning ? " · missing" : ""}
            </span>
          </button>
        );
      })}
    </nav>
  );
}

interface ServerPaneProps {
  server: McpServerSummary;
  filter: string;
  onFilterChange: (v: string) => void;
}

function McpServerPane({ server, filter, onFilterChange }: ServerPaneProps) {
  const trimmed = filter.trim().toLowerCase();
  const visibleTools = trimmed
    ? server.tools.filter(
        (t) =>
          t.name.toLowerCase().includes(trimmed) ||
          (t.description ?? "").toLowerCase().includes(trimmed),
      )
    : server.tools;

  return (
    <div className="px-6 py-4">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <h2 className="font-mono text-base font-semibold text-foreground">{server.name}</h2>
          {server.source_file && (
            <div className="mt-0.5 text-xs text-muted-foreground">
              <code className="rounded bg-muted/40 px-1.5 py-0.5 font-mono">{server.source_file}</code>
            </div>
          )}
        </div>
        <div className="text-xs text-muted-foreground">
          <strong className="text-foreground">{server.tools.length}</strong> atoms
        </div>
      </div>

      {server.warning && (
        <div className="mt-3 rounded-md border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-xs text-status-warning">
          {server.warning}
        </div>
      )}

      {server.tools.length > 0 && (
        <div className="mt-4">
          <input
            type="text"
            value={filter}
            onChange={(e) => onFilterChange(e.target.value)}
            placeholder="Filter tools…"
            className="w-full rounded-md border border-border bg-card px-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      )}

      <ul className="mt-3 flex flex-col gap-2">
        {visibleTools.map((tool) => (
          <McpToolRow key={tool.name} tool={tool} />
        ))}
        {visibleTools.length === 0 && server.tools.length > 0 && (
          <li className="rounded-md border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
            No tools match “{filter}”.
          </li>
        )}
      </ul>
    </div>
  );
}

function McpToolRow({ tool }: { tool: McpToolSummary }) {
  const [open, setOpen] = useState(false);
  const hasUsage = tool.used_by.length > 0;

  return (
    <li className="overflow-hidden rounded-md border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-accent"
      >
        <div className="min-w-0 flex-1">
          <div className="font-mono text-xs font-semibold text-foreground">{tool.name}</div>
          {tool.description && (
            <div className="mt-0.5 truncate text-xs text-muted-foreground">{tool.description}</div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2 text-[10px] text-muted-foreground">
          <span>
            {tool.params.length} {tool.params.length === 1 ? "param" : "params"}
          </span>
          {hasUsage && (
            <span className="rounded-full bg-status-info/15 px-2 py-0.5 font-medium text-status-info">
              {tool.used_by.length} skill{tool.used_by.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
      </button>
      {open && (
        <div className="border-t border-border bg-background/40 px-3 py-2 text-xs">
          {tool.description && (
            <p className="text-muted-foreground">{tool.description}</p>
          )}
          {tool.params.length > 0 && (
            <div className="mt-2">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Parameters
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {tool.params.map((p) => (
                  <code
                    key={p}
                    className="rounded bg-muted/50 px-1.5 py-0.5 font-mono text-[11px] text-foreground"
                  >
                    {p}
                  </code>
                ))}
              </div>
            </div>
          )}
          {hasUsage && (
            <div className="mt-2">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Used by
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {tool.used_by.map((skill) => (
                  <span
                    key={skill}
                    className="rounded-full bg-status-info/10 px-2 py-0.5 font-mono text-[11px] text-status-info"
                  >
                    {skill}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </li>
  );
}
