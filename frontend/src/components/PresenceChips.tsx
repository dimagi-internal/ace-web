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
    return <div className="text-sm text-zinc-400">nobody else here</div>;
  }
  return (
    <div className="flex gap-2">
      {present.map((p) => {
        const isHolder = p.user_id === draftHolderId && !draftHolderIdle;
        return (
          <div
            key={p.user_id}
            title={p.display_name + (isHolder ? " — editing…" : "")}
            className={`rounded-full px-2 py-1 text-xs ${
              isHolder
                ? "bg-amber-200 text-amber-900"
                : "bg-zinc-200 text-zinc-700"
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
