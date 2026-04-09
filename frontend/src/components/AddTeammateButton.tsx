import { useState } from "react";

import { addParticipant } from "../api/participants";

interface Props {
  slug: string;
  onAdded?: () => void;
}

export function AddTeammateButton({ slug, onAdded }: Props) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await addParticipant(slug, email.trim().toLowerCase());
      setOpen(false);
      setEmail("");
      onAdded?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to add teammate");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        className="rounded border border-zinc-300 px-2 py-1 text-xs text-zinc-600 hover:bg-zinc-100"
        onClick={() => setOpen(true)}
      >
        + teammate
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <input
        type="email"
        placeholder="name@dimagi.com"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        className="rounded border border-zinc-300 px-2 py-1 text-xs"
      />
      <button
        type="button"
        disabled={submitting || !email.includes("@")}
        className="rounded bg-blue-600 px-2 py-1 text-xs text-white disabled:opacity-40"
        onClick={submit}
      >
        add
      </button>
      <button
        type="button"
        className="text-xs text-zinc-500"
        onClick={() => {
          setOpen(false);
          setError(null);
        }}
      >
        cancel
      </button>
      {error ? <span className="text-xs text-rose-600">{error}</span> : null}
    </div>
  );
}
