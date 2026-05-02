import { Sparkles } from "lucide-react";

interface Suggestion {
  label: string;
  prompt: string;
}

const SUGGESTIONS: Suggestion[] = [
  {
    label: "List active ACE opportunities",
    prompt: "/ace:status",
  },
  {
    label: "Run /ace:doctor",
    prompt: "/ace:doctor",
  },
  {
    label: "Show MCP servers wired into the ACE plugin",
    prompt:
      "Show me which MCP servers are wired into the ACE plugin and what each one does.",
  },
];

interface Props {
  onUseSuggestion?: (prompt: string) => void;
}

export function WelcomePanel({ onUseSuggestion }: Props) {
  return (
    <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center px-6 py-10 text-center">
      <div className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Sparkles className="h-5 w-5" aria-hidden="true" />
      </div>
      <h2 className="mb-2 text-lg font-semibold text-foreground">
        Start a new chat
      </h2>
      <p className="mb-6 text-sm text-muted-foreground">
        This chat runs against your local Claude CLI subscription. Type
        anything below, or pick a starter:
      </p>
      <div className="flex w-full flex-col gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s.prompt}
            type="button"
            onClick={() => onUseSuggestion?.(s.prompt)}
            disabled={!onUseSuggestion}
            className="rounded-lg border border-border bg-background px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
          >
            {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}
