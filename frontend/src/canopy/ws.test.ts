import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * I2: ws.ts's buildCanopyWsUrl had no tests — it's the one function that
 * decides where the browser's chat socket actually connects, for both of
 * `CanopyStatus.base_url`'s two real shapes (a same-origin path in dev/labs,
 * or an absolute host when canopy runs elsewhere), and it reads the
 * delegated token synchronously (no await) via `peekCanopyToken()`.
 */

const peekCanopyTokenMock = vi.fn();
vi.mock("./token", () => ({
  peekCanopyToken: (...args: unknown[]) => peekCanopyTokenMock(...args),
}));

describe("buildCanopyWsUrl", () => {
  beforeEach(() => {
    vi.resetModules();
    peekCanopyTokenMock.mockReset();
  });

  it("builds a ws:// URL from window.location + a bare-path base, with ?token=", async () => {
    peekCanopyTokenMock.mockReturnValue("tok-123");
    const { buildCanopyWsUrl } = await import("./ws");

    const url = buildCanopyWsUrl("/canopy", "sess-1");

    // jsdom's default test origin is http://localhost:3000 (see
    // vitest.config.ts) — ws:// (not wss://) for a non-https origin.
    expect(url).toBe("ws://localhost:3000/canopy/ws/canopy-sessions/sess-1/?token=tok-123");
  });

  it("strips a trailing slash from a bare-path base before appending the ws path", async () => {
    peekCanopyTokenMock.mockReturnValue("tok-123");
    const { buildCanopyWsUrl } = await import("./ws");

    const url = buildCanopyWsUrl("/canopy/", "sess-1");

    expect(url).toBe("ws://localhost:3000/canopy/ws/canopy-sessions/sess-1/?token=tok-123");
  });

  it("builds a wss:// URL from an absolute https:// base, using ITS host (not window.location's)", async () => {
    peekCanopyTokenMock.mockReturnValue("tok-abc");
    const { buildCanopyWsUrl } = await import("./ws");

    const url = buildCanopyWsUrl("https://canopy.example.com/canopy", "sess-1");

    expect(url).toBe(
      "wss://canopy.example.com/canopy/ws/canopy-sessions/sess-1/?token=tok-abc",
    );
  });

  it("builds a ws:// URL from an absolute http:// base", async () => {
    peekCanopyTokenMock.mockReturnValue("tok-abc");
    const { buildCanopyWsUrl } = await import("./ws");

    const url = buildCanopyWsUrl("http://canopy.internal:8000", "sess-1");

    expect(url).toBe(
      "ws://canopy.internal:8000/ws/canopy-sessions/sess-1/?token=tok-abc",
    );
  });

  it("omits ?token= entirely when no token has been minted yet", async () => {
    peekCanopyTokenMock.mockReturnValue(null);
    const { buildCanopyWsUrl } = await import("./ws");

    const url = buildCanopyWsUrl("/canopy", "sess-1");

    expect(url).toBe("ws://localhost:3000/canopy/ws/canopy-sessions/sess-1/");
  });

  it("URI-encodes the session id and reads a fresh token on every call", async () => {
    peekCanopyTokenMock.mockReturnValueOnce("tok-1").mockReturnValueOnce("tok-2");
    const { buildCanopyWsUrl } = await import("./ws");

    const first = buildCanopyWsUrl("/canopy", "sess with space");
    const second = buildCanopyWsUrl("/canopy", "sess with space");

    expect(first).toBe(
      "ws://localhost:3000/canopy/ws/canopy-sessions/sess%20with%20space/?token=tok-1",
    );
    expect(second).toBe(
      "ws://localhost:3000/canopy/ws/canopy-sessions/sess%20with%20space/?token=tok-2",
    );
    expect(peekCanopyTokenMock).toHaveBeenCalledTimes(2);
  });
});
