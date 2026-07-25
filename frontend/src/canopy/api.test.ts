import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * I2: api.ts had ZERO tests before this — every canopy contract assumption
 * (field mappings, query params, the 401-retry-once path, origin_key) lived
 * here unverified, and a wrong constant in this exact file already produced
 * this branch's only Critical (fix-round-1's runner-status case bug).
 *
 * Two call shapes are mocked at their respective boundaries, never the
 * module under test itself:
 *  - `createCanopySession` goes through ace's own typed `apiClient` (mocked
 *    like token.test.ts/CanopyChatPanel.test.tsx do).
 *  - Everything else is a raw `fetch` to canopy-web directly (mocked via
 *    `global.fetch`, matching the existing pattern in
 *    `OppCard.test.tsx`), with `./token`'s `getCanopyToken` mocked so the
 *    401-retry-with-force path is exercised deterministically.
 */

const postMock = vi.fn();
vi.mock("../api/apiClient", () => ({
  apiClient: {
    POST: (...args: unknown[]) => postMock(...args),
  },
}));

const getCanopyTokenMock = vi.fn();
vi.mock("./token", () => ({
  getCanopyToken: (...args: unknown[]) => getCanopyTokenMock(...args),
}));

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("canopy/api.ts", () => {
  const originalFetch = global.fetch;
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    postMock.mockReset();
    getCanopyTokenMock.mockReset();
    fetchMock.mockReset();
    global.fetch = fetchMock as unknown as typeof global.fetch;
    getCanopyTokenMock.mockResolvedValue("tok-1");
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  // --- aceOriginKey -----------------------------------------------------

  it("aceOriginKey derives 'ace-web:<slug>' — must match apps/canopy/api.py's server-side derivation exactly", async () => {
    const { aceOriginKey } = await import("./api");
    expect(aceOriginKey("team-a")).toBe("ace-web:team-a");
    expect(aceOriginKey("team-b")).toBe("ace-web:team-b");
  });

  // --- listCanopySessions -------------------------------------------------

  it("listCanopySessions always sends source=ace-web and maps SessionOut fields (last_activity_at -> updated_at, runner_online passthrough, no metadata)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, [
        {
          id: "s-1",
          title: "Chat",
          agent_slug: "ace",
          last_activity_at: "2026-07-25T00:00:00Z",
          runner_name: "runner-a",
          runner_online: false,
          metadata: { origin_key: "ace-web:team-a" }, // must NOT leak through
        },
      ]),
    );
    const { listCanopySessions } = await import("./api");

    const rows = await listCanopySessions("/canopy");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/canopy/api/canopy-sessions/?source=ace-web");
    expect(rows).toEqual([
      {
        id: "s-1",
        title: "Chat",
        agent_slug: "ace",
        updated_at: "2026-07-25T00:00:00Z",
        runner_name: "runner-a",
        runner_online: false,
      },
    ]);
    expect(rows[0]).not.toHaveProperty("metadata");
  });

  it("listCanopySessions sends origin_key (and opp_slug/opp_run_id/state) as query params when provided (C1)", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, []));
    const { listCanopySessions } = await import("./api");

    await listCanopySessions("/canopy", {
      opp_slug: "field-hep",
      opp_run_id: "run-1",
      state: "active",
      origin_key: "ace-web:team-a",
    });

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string, "http://x");
    expect(parsed.searchParams.get("source")).toBe("ace-web");
    expect(parsed.searchParams.get("opp_slug")).toBe("field-hep");
    expect(parsed.searchParams.get("opp_run_id")).toBe("run-1");
    expect(parsed.searchParams.get("state")).toBe("active");
    expect(parsed.searchParams.get("origin_key")).toBe("ace-web:team-a");
  });

  it("listCanopySessions omits origin_key entirely when not provided (no ace workspace to scope by)", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, []));
    const { listCanopySessions } = await import("./api");

    await listCanopySessions("/canopy");

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string, "http://x");
    expect(parsed.searchParams.has("origin_key")).toBe(false);
  });

  // --- getCanopySession ----------------------------------------------------

  it("getCanopySession maps has_more_before/oldest_loaded_turn_index alongside the summary fields", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        id: "s-1",
        title: "Chat",
        agent_slug: null,
        last_activity_at: "now",
        runner_name: null,
        runner_online: null,
        has_more_before: true,
        oldest_loaded_turn_index: 5,
      }),
    );
    const { getCanopySession } = await import("./api");

    const detail = await getCanopySession("/canopy", "s-1");

    expect(detail).toEqual({
      id: "s-1",
      title: "Chat",
      agent_slug: null,
      updated_at: "now",
      runner_name: null,
      runner_online: null,
      has_more_before: true,
      oldest_loaded_turn_index: 5,
    });
    expect(fetchMock.mock.calls[0][0]).toBe("/canopy/api/canopy-sessions/s-1");
  });

  // --- createCanopySession (workspace-scoped, typed apiClient) ------------

  it("createCanopySession POSTs to the workspace-scoped route with the workspace_slug path param and defaulted body fields", async () => {
    postMock.mockResolvedValueOnce({
      data: { id: "sess-9" },
      response: { ok: true, status: 200 },
    });
    const { createCanopySession } = await import("./api");

    const result = await createCanopySession("team-a", { title: "Discuss" });

    expect(result).toEqual({ id: "sess-9" });
    expect(postMock).toHaveBeenCalledWith("/api/w/{workspace_slug}/canopy/sessions", {
      params: { path: { workspace_slug: "team-a" } },
      body: { title: "Discuss", opp_slug: "", opp_run_id: "", opp_step_skill: "" },
    });
  });

  it("createCanopySession throws on a non-ok response rather than returning undefined", async () => {
    postMock.mockResolvedValueOnce({
      data: undefined,
      response: { ok: false, status: 404 },
    });
    const { createCanopySession } = await import("./api");

    await expect(createCanopySession("team-a", {})).rejects.toThrow(/404/);
  });

  // --- fetchOlderMessages: unwraps {messages, has_more_before} ------------

  it("fetchOlderMessages unwraps the {messages, has_more_before} page shape", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { messages: [{ turn_index: 1 }], has_more_before: true }),
    );
    const { fetchOlderMessages } = await import("./api");

    const page = await fetchOlderMessages("/canopy", "s-1", 5);

    expect(page).toEqual({ messages: [{ turn_index: 1 }], has_more_before: true });
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/canopy/api/canopy-sessions/s-1/messages?before=5",
    );
  });

  // --- placeCanopySession: {runner_id} flattens to a wire string ---------

  it("placeCanopySession sends the literal string 'wait' unchanged", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));
    const { placeCanopySession } = await import("./api");

    await placeCanopySession("/canopy", "s-1", "wait");

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ placement: "wait" });
  });

  it("placeCanopySession flattens {runner_id} into the bare runner id string", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));
    const { placeCanopySession } = await import("./api");

    await placeCanopySession("/canopy", "s-1", { runner_id: "r-42" });

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ placement: "r-42" });
  });

  // --- 401-retry-once-with-force ------------------------------------------

  it("retries exactly once with a forced token refresh on a 401, then succeeds", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, {}))
      .mockResolvedValueOnce(jsonResponse(200, []));
    getCanopyTokenMock.mockResolvedValueOnce("tok-1").mockResolvedValueOnce("tok-2");
    const { listCanopySessions } = await import("./api");

    const rows = await listCanopySessions("/canopy");

    expect(rows).toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getCanopyTokenMock).toHaveBeenNthCalledWith(1);
    expect(getCanopyTokenMock).toHaveBeenNthCalledWith(2, true);
    // Both attempts carry a Bearer token, the second one the freshly forced one.
    const firstHeaders = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    const secondHeaders = fetchMock.mock.calls[1][1].headers as Record<string, string>;
    expect(firstHeaders.Authorization).toBe("Bearer tok-1");
    expect(secondHeaders.Authorization).toBe("Bearer tok-2");
  });

  it("does not retry a second time — a 401 after the forced retry still throws", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, {}))
      .mockResolvedValueOnce(jsonResponse(401, {}));
    getCanopyTokenMock.mockResolvedValueOnce("tok-1").mockResolvedValueOnce("tok-2");
    const { listCanopySessions } = await import("./api");

    await expect(listCanopySessions("/canopy")).rejects.toThrow(/401/);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  // --- listCanopyRunners: status -> live_status rename --------------------

  it("listCanopyRunners renames the wire 'status' field to live_status", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, [
        { id: "r-1", name: "runner-a", status: "online", ready: true, capabilities: { sessions: true } },
      ]),
    );
    const { listCanopyRunners } = await import("./api");

    const runners = await listCanopyRunners("/canopy");

    expect(runners).toEqual([
      { id: "r-1", name: "runner-a", live_status: "online", ready: true, capabilities: { sessions: true } },
    ]);
    expect(fetchMock.mock.calls[0][0]).toBe("/canopy/api/harness/runners/");
  });
});
