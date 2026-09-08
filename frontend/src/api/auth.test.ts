import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * `src/api/auth.ts` had NO tests, and three of its calls read the response body
 * a second time — `await response.json()` after `apiClient` had already consumed
 * it to build `data`. That throws "body stream already read" every single time,
 * so `promoteCliAuthToGlobal`, `disconnectNova` and `getCurrentUser`'s fallback
 * were dead on arrival in production. Nothing noticed, because nothing here ran.
 *
 * The mock therefore models what openapi-fetch ACTUALLY returns — `{data, error,
 * response}` with the body SPENT. A `json()` that throws is the whole point: it
 * is what makes a reintroduced double-read fail here instead of on the deployed
 * site.
 */

const getMock = vi.fn();
const postMock = vi.fn();

vi.mock("./apiClient", () => ({
  apiClient: {
    GET: (...args: unknown[]) => getMock(...args),
    POST: (...args: unknown[]) => postMock(...args),
  },
}));

/** openapi-fetch consumes the stream; a second read is a TypeError, not data. */
const spent = () => async () => {
  throw new TypeError(
    "Failed to execute 'json' on 'Response': body stream already read",
  );
};

const ok = (data: unknown) => ({
  data,
  error: undefined,
  response: { ok: true, status: 200, json: spent() },
});

const failed = (status = 500) => ({
  data: undefined,
  error: { detail: "boom" },
  response: { ok: false, status, json: spent() },
});

beforeEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});

describe("auth.ts against a real openapi-fetch response shape", () => {
  it("promoteCliAuthToGlobal uses the parsed body, not a second read", async () => {
    postMock.mockResolvedValueOnce(ok({ promoted: true, scope: "global" }));
    const { promoteCliAuthToGlobal } = await import("./auth");
    await expect(promoteCliAuthToGlobal()).resolves.toMatchObject({ promoted: true });
  });

  it("promoteCliAuthToGlobal reports the status when the call fails", async () => {
    postMock.mockResolvedValueOnce(failed(503));
    const { promoteCliAuthToGlobal } = await import("./auth");
    await expect(promoteCliAuthToGlobal()).rejects.toThrow(/503/);
  });

  it("disconnectNova uses the parsed body", async () => {
    postMock.mockResolvedValueOnce(ok({ disconnected: true }));
    const { disconnectNova } = await import("./auth");
    await expect(disconnectNova()).resolves.toEqual({ disconnected: true });
  });

  it("disconnectNova reports the status when the call fails", async () => {
    postMock.mockResolvedValueOnce(failed(500));
    const { disconnectNova } = await import("./auth");
    await expect(disconnectNova()).rejects.toThrow(/500/);
  });

  it("getCurrentUser maps the parsed body", async () => {
    getMock.mockResolvedValueOnce(
      ok({ id: 7, email: "ace@dimagi-ai.com", display_name: "ACE" }),
    );
    const { getCurrentUser } = await import("./auth");
    await expect(getCurrentUser()).resolves.toEqual({
      user_id: 7,
      email: "ace@dimagi-ai.com",
      display_name: "ACE",
    });
  });

  it("getCurrentUser says WHAT went wrong when no body was parsed", async () => {
    // The `content?: never` fallback. It used to attempt a second read, which
    // could only ever produce a TypeError about a spent stream — an error that
    // describes the plumbing rather than the failure. An empty `data` IS the
    // failure, so it says that, and it carries the status so the reader knows
    // whether it was a 204, a shape mismatch, or something else.
    getMock.mockResolvedValueOnce({
      data: undefined,
      error: undefined,
      response: { ok: true, status: 204, json: spent() },
    });
    const { getCurrentUser } = await import("./auth");
    await expect(getCurrentUser()).rejects.toThrow(/parsed no body \(status 204\)/);
  });
});
