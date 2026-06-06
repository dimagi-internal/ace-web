import { describe, it, expect, vi } from "vitest";
import { buildNarrationPrompt, generateNarration } from "./narration";
import type { ProgramSpec } from "./spec";

const sampleSpec: ProgramSpec = {
  slug: "mbw",
  name: "Mother-Baby Wellness",
  country_focus: "Nigeria",
  status: "Piloting 2026",
  tagline: "EBF and maternal mental health.",
  program_url: "https://labs.connect.dimagi.com/",
  scene: { clips: ["a.jpg"], lower_third: "Nigeria · 2026" },
  problem: { big: "29%", caption: "EBF rate", source: "NDHS 2018" },
  product: { beats: [{ asset: "x.mp4", caption: "y", start_seconds: 0, is_demo_clip: false }] },
  impact: [
    { big: "$320K", caption: "grant" },
    { big: "2,000", caption: "pairs" },
  ],
  narration: { generator: "anthropic", prompt_version: "v1", script: "", start_seconds: 0 },
  voice: { provider: "elevenlabs", voice_id: "v", model: "eleven_turbo_v2" },
};

describe("buildNarrationPrompt", () => {
  it("embeds every quantitative claim from the spec", () => {
    const prompt = buildNarrationPrompt(sampleSpec, { wordsPerMinute: 150, durationSeconds: 45 });
    expect(prompt).toContain("29%");
    expect(prompt).toContain("$320K");
    expect(prompt).toContain("2,000");
    expect(prompt).toContain("NDHS 2018");
    expect(prompt).toContain("Mother-Baby Wellness");
  });

  it("computes a target word count from duration and WPM", () => {
    const prompt = buildNarrationPrompt(sampleSpec, { wordsPerMinute: 160, durationSeconds: 30 });
    expect(prompt).toMatch(/about 80 words/i);
  });
});

describe("generateNarration", () => {
  it("returns the model's response text", async () => {
    const fakeClient = {
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [{ type: "text", text: "Generated narration." }],
        }),
      },
    };
    const out = await generateNarration(sampleSpec, {
      durationSeconds: 45,
      wordsPerMinute: 150,
      client: fakeClient as never,
    });
    expect(out).toBe("Generated narration.");
    expect(fakeClient.messages.create).toHaveBeenCalledOnce();
  });
});
