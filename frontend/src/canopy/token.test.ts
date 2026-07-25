import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Tests for token.ts's cached delegated-token lifecycle.
 *
 * The ace API helper (`apiClient`) is mocked — these tests never hit real
 * fetch. `vi.resetModules()` + a dynamic `import("./token")` per test gives
 * each test its own fresh module-level cache (the thing under test), while
 * fake timers let us cross the expiry/refresh-skew boundary deterministically.
 */

const postMock = vi.fn();

vi.mock("../api/apiClient", () => ({
  apiClient: {
    POST: (...args: unknown[]) => postMock(...args),
  },
}));

function mockTokenResponse(token: string, expiresAt: string) {
  postMock.mockResolvedValueOnce({
    response: {
      ok: true,
      status: 200,
      json: async () => ({ token, expires_at: expiresAt }),
    },
  });
}

describe("getCanopyToken / peekCanopyToken", () => {
  beforeEach(() => {
    vi.resetModules();
    postMock.mockReset();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-25T00:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("fetches on the first call", async () => {
    const { getCanopyToken, peekCanopyToken } = await import("./token");
    mockTokenResponse("tok-1", "2026-07-25T01:00:00.000Z");

    const token = await getCanopyToken();

    expect(token).toBe("tok-1");
    expect(postMock).toHaveBeenCalledTimes(1);
    expect(postMock.mock.calls[0][0]).toBe("/api/canopy/token");
    expect(peekCanopyToken()).toBe("tok-1");
  });

  it("returns the cached token on a second call within the TTL, without a fetch", async () => {
    const { getCanopyToken } = await import("./token");
    mockTokenResponse("tok-1", "2026-07-25T01:00:00.000Z");
    await getCanopyToken();

    vi.setSystemTime(new Date("2026-07-25T00:10:00.000Z")); // well inside the 1h TTL
    const token = await getCanopyToken();

    expect(token).toBe("tok-1");
    expect(postMock).toHaveBeenCalledTimes(1);
  });

  it("refetches once the clock passes expires_at - 5min", async () => {
    const { getCanopyToken } = await import("./token");
    mockTokenResponse("tok-1", "2026-07-25T01:00:00.000Z");
    await getCanopyToken();
    mockTokenResponse("tok-2", "2026-07-25T02:00:00.000Z");

    vi.setSystemTime(new Date("2026-07-25T00:56:00.000Z")); // inside the 5-min refresh skew
    const token = await getCanopyToken();

    expect(token).toBe("tok-2");
    expect(postMock).toHaveBeenCalledTimes(2);
  });

  it("force always refetches, even well within the TTL", async () => {
    const { getCanopyToken } = await import("./token");
    mockTokenResponse("tok-1", "2026-07-25T01:00:00.000Z");
    await getCanopyToken();
    mockTokenResponse("tok-2", "2026-07-25T01:30:00.000Z");

    const token = await getCanopyToken(true);

    expect(token).toBe("tok-2");
    expect(postMock).toHaveBeenCalledTimes(2);
  });

  it("a 401-triggered forced refresh (getCanopyToken(true)) returns the newly minted token", async () => {
    const { getCanopyToken, peekCanopyToken } = await import("./token");
    mockTokenResponse("tok-1", "2026-07-25T01:00:00.000Z");
    await getCanopyToken();

    // Simulate api.ts's retry-once-on-401 path: canopy rejected tok-1, so the
    // caller forces a refresh before retrying the request.
    mockTokenResponse("tok-2", "2026-07-25T02:00:00.000Z");
    const refreshed = await getCanopyToken(true);

    expect(refreshed).toBe("tok-2");
    expect(peekCanopyToken()).toBe("tok-2");
    expect(postMock).toHaveBeenCalledTimes(2);
  });

  it("peekCanopyToken is null before any token has been fetched", async () => {
    const { peekCanopyToken } = await import("./token");
    expect(peekCanopyToken()).toBeNull();
  });
});
