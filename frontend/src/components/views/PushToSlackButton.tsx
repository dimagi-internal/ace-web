import { useCallback, useEffect, useState } from "react";
import { ExternalLink, Hash, Lock, Send } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  getSlackPushInfo,
  listSlackChannels,
  pushPhaseToSlack,
  type SlackChannel,
  type SlackPushInfo,
} from "@/api/slack";

interface Props {
  workspaceSlug: string;
  oppSlug: string;
  runId: string;
  phaseName: string;
  phaseDisplay: string;
}

/**
 * Push the current phase to a Slack channel — replaces "go remember
 * `/ace track <slug>/<run_id>`". When a SlackRunThread already exists
 * for this (opp, run) the button switches to "Tracked in Slack" with
 * a deep link to the parent thread.
 *
 * Lazy: the channel list is fetched only when the user opens the
 * dialog (Slack's conversations.list is tier-2 rate-limited).
 */
export function PushToSlackButton({
  workspaceSlug,
  oppSlug,
  runId,
  phaseName,
  phaseDisplay,
}: Props) {
  const [pushInfo, setPushInfo] = useState<SlackPushInfo | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [channels, setChannels] = useState<SlackChannel[] | null>(null);
  const [channelsError, setChannelsError] = useState<string | null>(null);
  const [channelsLoading, setChannelsLoading] = useState(false);
  const [selectedChannel, setSelectedChannel] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);

  const refreshPushInfo = useCallback(() => {
    getSlackPushInfo(workspaceSlug, oppSlug, runId)
      .then(setPushInfo)
      .catch(() => setPushInfo({ installed: false, threads: [] }));
  }, [workspaceSlug, oppSlug, runId]);

  useEffect(() => {
    refreshPushInfo();
  }, [refreshPushInfo]);

  const handleOpen = () => {
    setDialogOpen(true);
    if (channels === null) {
      setChannelsLoading(true);
      listSlackChannels(workspaceSlug)
        .then((r) => {
          setChannels([...r.channels]);
          setChannelsError(r.hint ?? (r.error ? `Slack error: ${r.error}` : null));
        })
        .catch((e) => {
          toast.error(e instanceof Error ? e.message : "Failed to load channels");
          setChannels([]);
        })
        .finally(() => setChannelsLoading(false));
    }
  };

  const handleSubmit = async () => {
    if (!selectedChannel) return;
    setSubmitting(true);
    try {
      const result = await pushPhaseToSlack(workspaceSlug, {
        opp_slug: oppSlug,
        run_id: runId,
        phase: phaseName,
        channel_id: selectedChannel,
      });
      toast.success("Pushed to Slack");
      setDialogOpen(false);
      setSelectedChannel("");
      refreshPushInfo();
      if (result.permalink) {
        window.open(result.permalink, "_blank");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Push failed");
    } finally {
      setSubmitting(false);
    }
  };

  // Nothing to render until we know install state.
  if (pushInfo === null) return null;

  // Slack not installed in this workspace — render nothing rather than
  // a disabled stub. The Workspace Settings panel is the right place
  // to discover "Slack is missing."
  if (!pushInfo.installed) return null;

  // Already-tracked state: show a link to the existing thread instead
  // of a duplicate "push" button. First active thread wins; if there's
  // somehow more than one, the others are reachable from the Workbench
  // anyway.
  if (pushInfo.threads.length > 0) {
    const t = pushInfo.threads[0];
    const label = `Tracked in Slack`;
    return (
      <Button
        variant="outline"
        size="sm"
        className="shrink-0 text-xs"
        onClick={() => {
          if (t.permalink) window.open(t.permalink, "_blank");
        }}
        title={`Mirrored in channel ${t.channel_id} — open thread`}
      >
        <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
        {label}
      </Button>
    );
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={handleOpen}
        className="shrink-0 text-xs"
        title={`Post ${phaseDisplay} to a Slack channel and mirror updates`}
      >
        <Send className="mr-1.5 h-3.5 w-3.5" />
        Push to Slack
      </Button>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Push to Slack</DialogTitle>
            <DialogDescription>
              Post a parent card for <span className="font-mono">{oppSlug}</span> /{" "}
              <span className="font-mono">{runId}</span> and the{" "}
              <strong>{phaseDisplay}</strong> tile to a channel. Subsequent run
              updates will mirror to that channel automatically.
            </DialogDescription>
          </DialogHeader>

          {channelsLoading && (
            <p className="text-sm text-muted-foreground">Loading channels…</p>
          )}
          {channels !== null && channels.length === 0 && !channelsLoading && (
            <div className={`rounded border p-3 text-sm ${
              channelsError
                ? "border-destructive bg-destructive/10 text-destructive"
                : "border-border text-muted-foreground"
            }`}>
              {channelsError ? (
                <p>{channelsError}</p>
              ) : (
                <>
                  <p>The ACE bot isn't in any channels yet.</p>
                  <p className="mt-2 text-xs">
                    Invite it with <code>/invite @ACE</code> in a Slack channel,
                    then reopen this dialog.
                  </p>
                </>
              )}
            </div>
          )}
          {channels && channels.length > 0 && (
            <ul
              className="max-h-72 divide-y divide-border overflow-y-auto rounded border border-border"
              role="listbox"
              aria-label="Channels the ACE bot is a member of"
            >
              {channels.map((c) => {
                const Icon = c.is_private ? Lock : Hash;
                const isSelected = selectedChannel === c.id;
                return (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedChannel(c.id)}
                      aria-pressed={isSelected}
                      className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent/40 ${
                        isSelected ? "bg-primary/10 text-foreground" : ""
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-mono">{c.name}</span>
                      <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                        {c.id}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={!selectedChannel || submitting}
            >
              {submitting ? "Pushing…" : "Push"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
