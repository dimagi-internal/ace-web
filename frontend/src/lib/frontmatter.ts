export type Frontmatter = Array<[string, string]>;

export interface ParsedMarkdown {
  metadata: Frontmatter | null;
  body: string;
}

const FRONTMATTER_RE = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/;

export function parseFrontmatter(content: string): ParsedMarkdown {
  const stripped = content.replace(/^\uFEFF/, "");
  const match = FRONTMATTER_RE.exec(stripped);
  if (!match) {
    return { metadata: null, body: content };
  }

  const pairs: Frontmatter = [];
  for (const rawLine of match[1].split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const colon = line.indexOf(":");
    if (colon <= 0) {
      return { metadata: null, body: content };
    }
    const key = line.slice(0, colon).trim();
    let value = line.slice(colon + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    pairs.push([key, value]);
  }

  return { metadata: pairs, body: stripped.slice(match[0].length) };
}
