import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Tests for useCanopyStatus.ts's module-cached status fetch — in particular
 * the Ledger minor fix: `useCanopyStatus()` alone can't distinguish "still
 * loading" from "the fetch failed" (both are `null`), which left
 * `CanopyChatRoutePage` stuck on "Loading…" forever after a status blip.
 * `useCanopyStatusFailed()` is the sibling hook that tells them apart.
 *
 * `apiClient` is mocked — these tests never hit real fetch.
 * `vi.resetModules()` + a dynamic `import("./useCanopyStatus")` per test
 * gives each test its own fresh module-level cache.
 */

const getMock = vi.fn();

vi.mock("../api/apiClient", () => ({
  apiClient: {
    GET: (...args: unknown[]) => getMock(...args),
  },
}));

function mockStatusResponse(body: Record<string, unknown>) {
  getMock.mockResolvedValueOnce({
    response: {
      ok: true,
      status: 200,
      json: async () => body,
    },
  });
}

function mockStatusFailure(status = 500) {
  getMock.mockResolvedValueOnce({
    response: {
      ok: false,
      status,
      json: async () => ({}),
    },
  });
}

const STATUS = { enabled: true, base_url: "/canopy", workspace: "ws-1", agent: "ace" };

describe("useCanopyStatus / useCanopyStatusFailed", () => {
  beforeEach(() => {
    vi.resetModules();
    getMock.mockReset();
  });

  it("resolves to the fetched status on success", async () => {
    const { useCanopyStatus } = await import("./useCanopyStatus");
    mockStatusResponse(STATUS);

    const { result } = renderHook(() => useCanopyStatus());

    expect(result.current).toBeNull(); // loading
    await waitFor(() => expect(result.current).toEqual(STATUS));
    expect(getMock).toHaveBeenCalledTimes(1);
    expect(getMock.mock.calls[0][0]).toBe("/api/canopy/status");
  });

  it("useCanopyStatusFailed stays false while loading and after success", async () => {
    const { useCanopyStatus, useCanopyStatusFailed } = await import("./useCanopyStatus");
    mockStatusResponse(STATUS);

    const { result: statusResult } = renderHook(() => useCanopyStatus());
    const { result: failedResult } = renderHook(() => useCanopyStatusFailed());

    expect(failedResult.current).toBe(false);
    await waitFor(() => expect(statusResult.current).toEqual(STATUS));
    expect(failedResult.current).toBe(false);
  });

  it("useCanopyStatus stays null and useCanopyStatusFailed flips true when the fetch fails", async () => {
    const { useCanopyStatus, useCanopyStatusFailed } = await import("./useCanopyStatus");
    mockStatusFailure(500);

    const { result: statusResult } = renderHook(() => useCanopyStatus());
    const { result: failedResult } = renderHook(() => useCanopyStatusFailed());

    await waitFor(() => expect(failedResult.current).toBe(true));
    // Both hooks observe the same failure — status never resolves to a value.
    expect(statusResult.current).toBeNull();
  });

  it("a later mount after a failure gets to try again (failure doesn't poison the cache forever)", async () => {
    const { useCanopyStatus, useCanopyStatusFailed } = await import("./useCanopyStatus");
    mockStatusFailure(500);

    const { result: failedResult, unmount } = renderHook(() => useCanopyStatusFailed());
    await waitFor(() => expect(failedResult.current).toBe(true));
    unmount();

    mockStatusResponse(STATUS);
    const { result: statusResult } = renderHook(() => useCanopyStatus());
    await waitFor(() => expect(statusResult.current).toEqual(STATUS));
    expect(getMock).toHaveBeenCalledTimes(2);
  });

  it("mounting both hooks at once shares one fetch (single in-flight request)", async () => {
    const { useCanopyStatus, useCanopyStatusFailed } = await import("./useCanopyStatus");
    mockStatusResponse(STATUS);

    const { result: statusResult } = renderHook(() => useCanopyStatus());
    renderHook(() => useCanopyStatusFailed());
    renderHook(() => useCanopyStatus());

    await waitFor(() => expect(statusResult.current).toEqual(STATUS));
    expect(getMock).toHaveBeenCalledTimes(1);
  });
});
