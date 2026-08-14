import type { ReviewerIdentity } from "./reviewerIdentity";

/**
 * Name + email, asked at the moment someone submits something.
 *
 * Shared by the comment box and the answer editor so the two never
 * disagree about what identity a partner is being asked for, or about
 * how it is explained to them.
 *
 * Not rendered at all for a signed-in viewer — the session identity is
 * used instead, and asking a member to type their name is both noise and
 * an invitation to type someone else's.
 */
export function ReviewerIdentityFields({
  identity,
  onChange,
  note,
}: {
  identity: ReviewerIdentity;
  onChange: (next: ReviewerIdentity) => void;
  note?: string;
}) {
  return (
    <>
      <div className="flex flex-wrap gap-2">
        <input
          value={identity.name}
          onChange={(e) => onChange({ ...identity, name: e.target.value })}
          maxLength={80}
          required
          placeholder="Your name (required)"
          aria-label="Your name"
          className="min-w-[9rem] flex-1 rounded border border-border bg-background px-3 py-1.5 text-[13px] text-foreground placeholder:text-muted-foreground/50 focus:border-primary focus:outline-none"
        />
        <input
          value={identity.email}
          onChange={(e) => onChange({ ...identity, email: e.target.value })}
          maxLength={254}
          type="email"
          placeholder="Email (optional)"
          aria-label="Your email, optional"
          className="min-w-[9rem] flex-1 rounded border border-border bg-background px-3 py-1.5 text-[13px] text-foreground placeholder:text-muted-foreground/50 focus:border-primary focus:outline-none"
        />
      </div>
      <p className="text-[11px] leading-[1.5] text-muted-foreground/70">
        {note ??
          "Your name is stored with the change so we can credit it and come back to you. Email is only used to reply."}
      </p>
    </>
  );
}
