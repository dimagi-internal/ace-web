import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, GitCompare } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import type { RunSummary } from "@/api/types";
import { CompareRunsDialog } from "./CompareRunsDialog";

interface Props {
  slug: string;
  currentRunId: string;
  runs: RunSummary[];
}

export function RunSelector({ slug, currentRunId, runs }: Props) {
  const navigate = useNavigate();
  const [compareOpen, setCompareOpen] = useState(false);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger render={<Button size="sm" variant="outline" />}>
          {currentRunId}
          <ChevronDown className="ml-1 h-3.5 w-3.5" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72">
          {runs.map((r) => (
            <DropdownMenuItem
              key={r.run_id}
              onClick={() => navigate(`/opps/${slug}/runs/${r.run_id}`)}
              className={r.run_id === currentRunId ? "font-semibold" : ""}
            >
              <span className="flex-1">{r.run_id}</span>
              <span className="ml-auto text-xs text-muted-foreground">{r.status}</span>
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => setCompareOpen(true)}>
            <GitCompare className="mr-2 h-3.5 w-3.5" />
            Compare runs…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <CompareRunsDialog
        open={compareOpen}
        onOpenChange={setCompareOpen}
        slug={slug}
        runs={runs}
      />
    </>
  );
}
