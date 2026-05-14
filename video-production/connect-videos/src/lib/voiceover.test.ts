import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { existsSync, rmSync, readFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";
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
    const fakeFetch = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new Uint8Array([1, 2, 3, 4]).buffer,
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
    const fakeFetch = vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new Uint8Array([1, 2, 3, 4]).buffer,
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
});
