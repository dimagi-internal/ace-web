import type { Participant } from "../api/types";

interface Props {
  participants: Participant[];
  presenceUserIds: number[];
  draftHolderId: number | null;
  draftHolderIdle: boolean;
}

export function PresenceChips({
  participants,
  presenceUserIds,
  draftHolderId,
  draftHolderIdle,
}: Props) {
  const present = participants.filter((p) =>
    presenceUserIds.includes(p.user_id),
  );
  if (present.length === 0) {
    return <div className="text-sm text-muted-foreground">nobody else here</div>;
  }
  return (
    <div className="flex gap-2">
      {present.map((p) => {
        const isHolder = p.user_id === draftHolderId && !draftHolderIdle;
        return (
          <div
            key={p.user_id}
            title={p.display_name + (isHolder ? " — editing…" : "")}
            className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-medium ${
              isHolder
                ? "bg-primary text-primary-foreground ring-2 ring-primary/30"
                : "bg-muted text-muted-foreground"
            }`}
          >
            {initials(p.display_name)}
          </div>
        );
      })}
    </div>
  );
}

function initials(name: string): string {
  return name
    .split(" ")
    .map((w) => w[0])
    .filter(Boolean)
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
