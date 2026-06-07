import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { existsSync, rmSync, readFileSync, mkdtempSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import { tmpdir } from "node:os";
import { synthesize, cacheKey } from "./voiceover";

let tmpDir: string;

beforeEach(() => {
  tmpDir = path.join(os.tmpdir(), `vo-${Date.now()}-${Math.random()}`);
});

afterEach(() => {
  if (existsSync(tmpDir)) rmSync(tmpDir, { recursive: true, force: true });
});

describe("cacheKey", () => {
  it("produces stable hashes for identical inputs", () => {
    expect(cacheKey("hi", "v1", "m1")).toBe(cacheKey("hi", "v1", "m1"));
  });
  it("differs when any input changes", () => {
    expect(cacheKey("hi", "v1", "m1")).not.toBe(cacheKey("hi!", "v1", "m1"));
    expect(cacheKey("hi", "v1", "m1")).not.toBe(cacheKey("hi", "v2", "m1"));
  });
});

describe("synthesize", () => {
  it("writes audio to cache and returns its path", async () => {
    // ElevenLabs /with-timestamps returns JSON { audio_base64, alignment };
    // voiceover.ts decodes audio_base64. (Older mock returned arrayBuffer().)
    const fakeFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ audio_base64: Buffer.from([1, 2, 3, 4]).toString("base64") }),
    });
    const out = await synthesize({
      script: "hello",
      voiceId: "v1",
      model: "m1",
      cacheDir: tmpDir,
      fetchImpl: fakeFetch as unknown as typeof fetch,
      apiKey: "test-key",
    });
    expect(existsSync(out)).toBe(true);
    expect(readFileSync(out).length).toBe(4);
    expect(fakeFetch).toHaveBeenCalledOnce();
  });

  it("returns the cached path on second call without re-fetching", async () => {
    // Cache validity requires a sidecar with alignment.characters, so the
    // second call only hits cache when the first wrote real alignment.
    const fakeFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        audio_base64: Buffer.from([1, 2, 3, 4]).toString("base64"),
        alignment: {
          characters: ["h", "i"],
          character_start_times_seconds: [0, 0.1],
          character_end_times_seconds: [0.1, 0.2],
        },
      }),
    });
    const args = {
      script: "hello",
      voiceId: "v1",
      model: "m1",
      cacheDir: tmpDir,
      fetchImpl: fakeFetch as unknown as typeof fetch,
      apiKey: "test-key",
    };
    await synthesize(args);
    await synthesize(args);
    expect(fakeFetch).toHaveBeenCalledOnce();
  });

  it("writes a sidecar JSON next to the mp3", async () => {
    const cacheDir = mkdtempSync(path.join(tmpdir(), "voiceover-sidecar-"));
    try {
      const fakeFetch: typeof fetch = async () =>
        new Response(
          JSON.stringify({
            audio_base64: Buffer.from([0xff, 0xfb, 0x10, 0xc0]).toString("base64"),
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      const out = await synthesize({
        script: "Hello world",
        voiceId: "voiceA",
        model: "modelB",
        cacheDir,
        apiKey: "key",
        fetchImpl: fakeFetch,
      });
      const stem = path.basename(out, ".mp3");
      const sidecarPath = path.join(cacheDir, `${stem}.json`);
      expect(existsSync(sidecarPath)).toBe(true);
      const parsed = JSON.parse(readFileSync(sidecarPath, "utf8"));
      expect(parsed.voice_id).toBe("voiceA");
      expect(parsed.model).toBe("modelB");
      expect(parsed.text).toBe("Hello world");
      expect(typeof parsed.generated_at).toBe("string");
      expect(
        parsed.duration_sec === null || typeof parsed.duration_sec === "number",
      ).toBe(true);
    } finally {
      rmSync(cacheDir, { recursive: true, force: true });
    }
  });

  it("returns cached path when both mp3 and sidecar exist", async () => {
    const cacheDir = mkdtempSync(path.join(tmpdir(), "voiceover-cached-"));
    try {
      let fetchCalls = 0;
      const fakeFetch: typeof fetch = async () => {
        fetchCalls++;
        return new Response(
          JSON.stringify({
            audio_base64: Buffer.from([0xff, 0xfb]).toString("base64"),
            // alignment.characters is required for the cache to be considered
            // valid — without it the second call re-synths (cache miss).
            alignment: {
              characters: ["T"],
              character_start_times_seconds: [0],
              character_end_times_seconds: [0.1],
            },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      };
      await synthesize({
        script: "Twice", voiceId: "v", model: "m",
        cacheDir, apiKey: "key", fetchImpl: fakeFetch,
      });
      await synthesize({
        script: "Twice", voiceId: "v", model: "m",
        cacheDir, apiKey: "key", fetchImpl: fakeFetch,
      });
      expect(fetchCalls).toBe(1);
    } finally {
      rmSync(cacheDir, { recursive: true, force: true });
    }
  });
});
