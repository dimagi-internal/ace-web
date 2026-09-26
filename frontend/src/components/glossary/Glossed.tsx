import { splitGlossary } from "@/lib/glossary";

/**
 * Renders `text` with every glossary term underlined (dotted) and defined on
 * hover. A native `<abbr title>` rather than a tooltip component: it works in
 * truncated and line-clamped labels, costs nothing per term, and screen
 * readers announce it.
 */
export function Glossed({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  const segments = splitGlossary(text);
  if (segments.every((s) => !s.definition)) return <>{text}</>;
  return (
    <>
      {segments.map((s, i) =>
        s.definition ? (
          <abbr
            key={i}
            title={s.definition}
            className="cursor-help underline decoration-muted-foreground/60 decoration-dotted underline-offset-2"
          >
            {s.text}
          </abbr>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </>
  );
}
