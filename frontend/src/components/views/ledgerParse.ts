/**
 * Parse the plugin's rendered feedback ledger into something worth reading.
 *
 * The ledger is a Google Doc exported as markdown, written to be read AS a
 * doc. Rendered raw in a panel it comes out as a wall: every disposition is
 * one long bullet joined by em dashes, each carrying a full GitHub URL as its
 * own link text (wrapping across two lines), and each repeating the same
 * "(run …)" that the panel header already states once.
 *
 * So we parse it. The format is machine-generated and regular:
 *
 *     ## \[a\] §3 Instrument — implement Annex A verbatim
 *     > the reviewer's words
 *     - **SHIPPED** · skill fix — ace#980 — what changed — [url](url) *(run X)*
 *
 * **Every function here returns null rather than guessing.** A parse that
 * half-matches is worse than no parse: the caller falls back to rendering the
 * markdown as-is, which is always correct and merely dense. That fallback is
 * what makes parsing a generated format safe — the plugin owns this output
 * and can change it, and when it does this degrades instead of lying.
 */

export interface Disposition {
  /** SHIPPED, UNROUTED, … — whatever the ledger bolded. */
  readonly status: string;
  /** "skill fix", "decision", "open question". */
  readonly kind: string;
  readonly text: string;
  /** Short label for the link, e.g. "ace#980". */
  readonly ref: string | null;
  readonly href: string | null;
}

export interface LedgerItem {
  readonly id: string;
  readonly anchor: string;
  readonly quote: string;
  readonly dispositions: readonly Disposition[];
}

/** Google's markdown export escapes punctuation that could read as syntax.
 *
 * Deliberately broad — any backslash before a non-word character. A fixed
 * list missed `\=`, which left `visit_outcome \= if(...)` on screen inside a
 * reviewer's own quoted words. */
function unescape(text: string): string {
  // NOT `[^\w\s]` — `_` is a word character, so that class silently skipped
  // `\_` and left `visit\_outcome` on screen inside a reviewer's own words.
  return text.replace(/\\([^A-Za-z0-9\s])/g, "$1");
}

/** "https://github.com/dimagi-internal/ace/issues/980" → "ace#980". */
function shortRef(href: string): string | null {
  const m = /github\.com\/[^/]+\/([^/]+)\/(?:issues|pull)\/(\d+)/.exec(href);
  return m ? `${m[1]}#${m[2]}` : null;
}

function parseDisposition(line: string): Disposition | null {
  // "- **SHIPPED** · skill fix — rest"
  const m = /^-\s+\*\*([^*]+)\*\*\s*(?:·\s*)?([^—–]*)(?:[—–]\s*)?([\s\S]*)$/.exec(line.trim());
  if (!m) return null;
  const status = m[1].trim();
  if (!status) return null;

  let rest = m[3].trim();
  const kind = unescape(m[2].trim());

  // The trailing "*(run 20260728-0705)*" repeats the header; drop it.
  rest = rest.replace(/\*\(run\s+[^)]*\)\*\s*$/i, "").trim();

  // A markdown link anywhere in the remainder is the disposition's reference.
  let href: string | null = null;
  const link = /\[([^\]]*)\]\((https?:\/\/[^)]+)\)/.exec(rest);
  if (link) {
    href = link[2];
    rest = rest.replace(link[0], "").trim();
  }

  // Whatever separator is left dangling once the link is removed.
  rest = rest.replace(/[\s—–-]+$/, "").trim();

  let ref = href ? (shortRef(href) ?? "link") : null;
  let text = unescape(rest);

  // The ledger repeats the reference inside the prose ("ace#980 — a parser
  // now rejects…"). With the ref shown as its own link, that is said twice.
  if (ref) {
    const dup = new RegExp(`^${ref.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*[—–-]\\s*`);
    text = text.replace(dup, "");
  }

  // A disposition with no URL still names what it changed, dangling off the
  // end: "… stay gated behind consent. — decisions.yaml#gps-capture-scope".
  // Promote it to the ref slot so every row reads the same way.
  if (!ref) {
    const trailing = /\s[—–]\s+([^\s—–]+)$/.exec(text);
    if (trailing) {
      ref = trailing[1];
      text = text.slice(0, trailing.index).trim();
    }
  }

  return { status, kind, text: text.trim(), ref, href };
}

function parseSection(section: string): LedgerItem | null {
  const lines = section.split("\n");
  const heading = unescape((lines.shift() ?? "").trim());
  if (!heading) return null;

  // "[a] §3 Instrument — implement Annex A verbatim"
  const h = /^\[([^\]]+)\]\s*(.*)$/.exec(heading);
  const id = h ? h[1].trim() : "";
  const anchor = (h ? h[2] : heading).trim();
  if (!anchor) return null;

  const quote: string[] = [];
  const dispositions: Disposition[] = [];
  for (const raw of lines) {
    const line = raw.trim();
    if (line.startsWith(">")) {
      const text = line.replace(/^>\s?/, "").trim();
      if (text) quote.push(unescape(text));
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      const d = parseDisposition(line.replace(/^\*\s/, "- "));
      if (d) dispositions.push(d);
    }
  }

  return { id, anchor, quote: quote.join("\n"), dispositions };
}

/**
 * The ledger's items, or null when the body isn't the shape we know.
 *
 * Null means "render the markdown instead" — never "show nothing".
 */
export function parseLedger(body: string): LedgerItem[] | null {
  if (!body || !body.trim()) return null;
  const sections = body.split(/^##\s+/m).slice(1);
  if (sections.length === 0) return null;
  const items = sections.map(parseSection).filter((i): i is LedgerItem => i !== null);
  if (items.length === 0) return null;
  // A parse that found headings but no dispositions anywhere has almost
  // certainly missed the format; the raw body is the safer render.
  if (items.every((i) => i.dispositions.length === 0)) return null;
  return items;
}

/**
 * What a disposition actually changed — the distinction the ledger's own
 * SHIPPED badge hides.
 *
 *   ace      — a fix to ACE itself (a skill). Every FUTURE program gets it.
 *              This is the self-improvement story.
 *   program  — a change to this one program's design (a run decision).
 *   person   — still waiting on a human (an open question, NEEDS YOU).
 *
 * Read off the ledger's own `kind` / status words, never inferred from prose.
 */
export type Outcome = "ace" | "program" | "person" | "other";

export function outcomeOf(d: Disposition): Outcome {
  const kind = d.kind.toLowerCase();
  const status = d.status.toLowerCase();
  if (status.includes("need") || kind.includes("question")) return "person";
  if (kind.includes("skill") || kind.includes("fix")) return "ace";
  if (kind.includes("decision")) return "program";
  return "other";
}

/** How many COMMENTS led to each outcome. A comment that produced both a skill
 *  fix and a decision counts under both — that's what happened. */
export function outcomeCounts(items: readonly LedgerItem[]): Record<Outcome, number> {
  const counts: Record<Outcome, number> = { ace: 0, program: 0, person: 0, other: 0 };
  for (const item of items) {
    const seen = new Set(item.dispositions.map(outcomeOf));
    for (const o of seen) counts[o] += 1;
  }
  return counts;
}
