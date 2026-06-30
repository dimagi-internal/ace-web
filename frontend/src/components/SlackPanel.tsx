import { useCallback, useEffect, useState } from "react";

import { Badge } from "@marshellis/workbench/ui";
import { Button } from "@marshellis/workbench/ui";
import { getSlackStatus, type SlackStatus } from "@/api/slack";

interface Props {
  workspaceSlug: string;
}

/**
 * Slack integration panel for Workspace Settings.
 *
 * One panel covers three states:
 *   - Not installed: show an "Add to Slack" CTA for users with manage
 *     permission; otherwise tell them who can do it.
 *   - Installed: show team + installer + age; link to the orphan test
 *     page (apps/slack/views_test_page.py) and offer Reconnect.
 *   - Loading / error: show plain text — no spinners, no skeletons.
 *
 * Closely mirrors the existing Nova MCP panel in SettingsPage for
 * visual + interaction consistency.
 */
export function SlackPanel({ workspaceSlug }: Props) {
  const [status, setStatus] = useState<SlackStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    getSlackStatus(workspaceSlug)
      .then(setStatus)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [workspaceSlug]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return (
      <section className="mt-8">
        <h2 className="text-lg font-medium text-foreground">Slack</h2>
        <p className="mt-1 text-sm text-destructive">{error}</p>
      </section>
    );
  }

  if (status === null) {
    return (
      <section className="mt-8">
        <h2 className="text-lg font-medium text-foreground">Slack</h2>
        <p className="mt-1 text-sm text-muted-foreground">Loading…</p>
      </section>
    );
  }

  return (
    <section className="mt-8">
      <h2 className="text-lg font-medium text-foreground">Slack</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        The ACE Slack bot lets you trigger runs (<code>/ace run</code>) and
        mirror progress into channels. Each workspace pairs with one Slack
        team.
      </p>

      <div className="mt-4 rounded border border-border p-4">
        <div className="flex items-center justify-between">
          <div>
            <div className="font-medium">Connection</div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              {status.installed
                ? `Connected to ${status.team_name ?? status.team_id}`
                : "Not installed in this workspace"}
            </div>
          </div>
          <Badge variant={status.installed ? "default" : "outline"}>
            {status.installed ? "Connected" : "Not installed"}
          </Badge>
        </div>

        {status.installed && (
          <div className="mt-3 space-y-1 text-xs text-muted-foreground">
            {status.installed_by_email && (
              <div>
                Installed by{" "}
                <span className="text-foreground">{status.installed_by_email}</span>
              </div>
            )}
            {status.installed_at && (
              <div>
                Installed on{" "}
                <span className="text-foreground">
                  {new Date(status.installed_at).toLocaleDateString()}
                </span>
              </div>
            )}
            {status.team_url && (
              <div>
                Team URL:{" "}
                <a
                  href={status.team_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-foreground hover:underline"
                >
                  {status.team_url}
                </a>
              </div>
            )}
          </div>
        )}

        <div className="mt-3 flex flex-wrap gap-2">
          {!status.installed && status.can_manage && status.install_url && (
            <Button
              size="sm"
              variant="default"
              onClick={() => {
                window.location.href = status.install_url ?? "";
              }}
            >
              Add to Slack
            </Button>
          )}
          {!status.installed && !status.can_manage && (
            <p className="text-xs text-muted-foreground">
              Ask an admin to connect Slack on this instance.
            </p>
          )}
          {status.installed && status.test_page_url && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                window.open(status.test_page_url ?? "", "_blank");
              }}
            >
              Open Block Kit preview
            </Button>
          )}
          {status.installed && status.can_manage && status.install_url && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                window.location.href = status.install_url ?? "";
              }}
            >
              Reconnect
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}
