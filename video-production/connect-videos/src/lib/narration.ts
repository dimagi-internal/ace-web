import Anthropic from "@anthropic-ai/sdk";
import type { ProgramSpec } from "./spec";

export interface NarrationOptions {
  wordsPerMinute: number;
  durationSeconds: number;
  client?: Anthropic;
}

export function buildNarrationPrompt(
  spec: ProgramSpec,
  opts: { wordsPerMinute: number; durationSeconds: number }
): string {
  const targetWords = Math.round((opts.wordsPerMinute * opts.durationSeconds) / 60);
  const productLines = spec.product.beats
    .map((b) => `  - ${b.caption}`)
    .join("\n");
  const impactLines = spec.impact
    .map((s) => `  - ${s.big} ${s.caption}`)
    .join("\n");
  return `You are writing a ~${opts.durationSeconds}-second narration script for a Connect by Dimagi program video. The narration plays over field footage, app screen recordings, and motion-graphic stat cards.

Audience: philanthropic funders and prospective local delivery organizations.
Tone: matter-of-fact, evidence-led, no marketing fluff. Verified delivery, not promises.
Length: about ${targetWords} words (at ${opts.wordsPerMinute} WPM).

PROGRAM: ${spec.name}
Country focus: ${spec.country_focus}
Status: ${spec.status}
Tagline: ${spec.tagline}

PROBLEM STAT (must appear): ${spec.problem.big} — ${spec.problem.caption}${spec.problem.source ? ` (Source: ${spec.problem.source})` : ""}

PRODUCT BEATS (in order, must be covered):
${productLines}

IMPACT STATS (must appear):
${impactLines}

Rules:
- Use only the numbers above. Do not invent quantitative claims.
- Open by setting the scene in ${spec.country_focus}.
- Touch the Connect cycle: Learn → Deliver → Verify → Pay.
- End with the impact stats.
- Output ONLY the narration text, no headings, no quotes, no stage directions.`;
}

export async function generateNarration(
  spec: ProgramSpec,
  opts: NarrationOptions
): Promise<string> {
  const client = opts.client ?? new Anthropic();
  const prompt = buildNarrationPrompt(spec, opts);
  const resp = await client.messages.create({
    model: "claude-sonnet-4-6",
    max_tokens: 800,
    messages: [{ role: "user", content: prompt }],
  });
  const text = resp.content
    .filter((c): c is { type: "text"; text: string } => c.type === "text")
    .map((c) => c.text)
    .join("\n")
    .trim();
  return text;
}
