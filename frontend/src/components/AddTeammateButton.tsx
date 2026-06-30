import { useState } from "react";

import { Button } from "@marshellis/canopy-ui/ui";
import { Input } from "@marshellis/canopy-ui/ui";
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
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 px-1.5 text-xs font-normal text-muted-foreground hover:text-foreground"
        onClick={() => setOpen(true)}
      >
        + teammate
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Input
        type="email"
        placeholder="name@dimagi.com"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        className="h-7 w-48 text-xs"
      />
      <Button
        type="button"
        size="sm"
        className="h-7 text-xs"
        disabled={submitting || !email.includes("@")}
        onClick={submit}
      >
        add
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 text-xs"
        onClick={() => {
          setOpen(false);
          setError(null);
        }}
      >
        cancel
      </Button>
      {error ? (
        <span className="text-xs text-destructive">{error}</span>
      ) : null}
    </div>
  );
}
