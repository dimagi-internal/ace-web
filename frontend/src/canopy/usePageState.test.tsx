import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CanopyPageStateRejected, type CanopyPageState } from "./api";
import { useCanopyPageState } from "./usePageState";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, declareCanopyPageState: vi.fn() };
});

const api = await import("./api");
const declare = vi.mocked(api.declareCanopyPageState);

const BASE = "/canopy";
const SESSION = "sess-1";

function stateFor(step: string): CanopyPageState {
  return {
    resource: "opp://bednet/run-001",
    backing_tool: "apps_opps_api_get_step",
    filters: { step_skill: step },
  };
}

beforeEach(() => {
  declare.mockReset();
  declare.mockResolvedValue(undefined);
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useCanopyPageState", () => {
  it("declares the page once a session exists", async () => {
    renderHook(() => useCanopyPageState(BASE, SESSION, stateFor("idea-to-pdd")));
    await waitFor(() => expect(declare).toHaveBeenCalledTimes(1));
    expect(declare).toHaveBeenCalledWith(BASE, SESSION, stateFor("idea-to-pdd"));
  });

  it.each([
    ["no canopy base", null, SESSION],
    ["no session yet", BASE, null],
  ])("declares nothing when there is %s", async (_label, base, session) => {
    // Declaring nothing is a legitimate state — the agent simply starts
    // without page state. It must not be an error, and it must not PUT.
    renderHook(() => useCanopyPageState(base, session, stateFor("idea-to-pdd")));
    await new Promise((r) => setTimeout(r, 10));
    expect(declare).not.toHaveBeenCalled();
  });

  it("does not re-send when a render produces an equal state", async () => {
    // The caller builds a fresh object every render. Comparing by identity
    // would PUT on every single render, forever.
    const { rerender } = renderHook(
      ({ step }) => useCanopyPageState(BASE, SESSION, stateFor(step)),
      { initialProps: { step: "idea-to-pdd" } },
    );
    await waitFor(() => expect(declare).toHaveBeenCalledTimes(1));
    rerender({ step: "idea-to-pdd" });
    rerender({ step: "idea-to-pdd" });
    await new Promise((r) => setTimeout(r, 10));
    expect(declare).toHaveBeenCalledTimes(1);
  });

  it("re-sends when the selection actually changes", async () => {
    const { rerender } = renderHook(
      ({ step }) => useCanopyPageState(BASE, SESSION, stateFor(step)),
      { initialProps: { step: "idea-to-pdd" } },
    );
    await waitFor(() => expect(declare).toHaveBeenCalledTimes(1));
    rerender({ step: "connect-setup" });
    await waitFor(() => expect(declare).toHaveBeenCalledTimes(2));
    expect(declare).toHaveBeenLastCalledWith(BASE, SESSION, stateFor("connect-setup"));
  });

  it("lets the NEWEST selection win when two changes race", async () => {
    // The bug this guards: canopy replaces page state wholesale, so if a slow
    // PUT for step A lands after a fast one for step B, the agent is left
    // reading A — which is exactly the staleness the hook exists to remove.
    const resolvers: (() => void)[] = [];
    declare.mockImplementation(
      () => new Promise<void>((resolve) => resolvers.push(resolve)),
    );

    const { rerender } = renderHook(
      ({ step }) => useCanopyPageState(BASE, SESSION, stateFor(step)),
      { initialProps: { step: "a" } },
    );
    await waitFor(() => expect(declare).toHaveBeenCalledTimes(1));

    // Two more selections while the first request is still open.
    rerender({ step: "b" });
    rerender({ step: "c" });
    expect(declare).toHaveBeenCalledTimes(1); // still serialised behind the first

    resolvers[0]();
    await waitFor(() => expect(declare).toHaveBeenCalledTimes(2));
    // "b" was superseded before it was ever sent, so it is dropped rather than
    // queued — the agent does not need a view that was on screen for 80ms.
    expect(declare).toHaveBeenLastCalledWith(BASE, SESSION, stateFor("c"));

    resolvers[1]();
    await new Promise((r) => setTimeout(r, 10));
    expect(declare).toHaveBeenCalledTimes(2);
  });

  it("survives a transient failure and retries on the next change", async () => {
    declare.mockRejectedValueOnce(new Error("offline"));
    const { rerender } = renderHook(
      ({ step }) => useCanopyPageState(BASE, SESSION, stateFor(step)),
      { initialProps: { step: "a" } },
    );
    await waitFor(() => expect(declare).toHaveBeenCalledTimes(1));

    declare.mockResolvedValue(undefined);
    rerender({ step: "b" });
    await waitFor(() => expect(declare).toHaveBeenCalledTimes(2));
    expect(declare).toHaveBeenLastCalledWith(BASE, SESSION, stateFor("b"));
  });

  it("does not spin on a payload canopy refuses outright", async () => {
    // `too_large` means the page sent rows where it should have sent ids.
    // Canopy will refuse it identically every time, so retrying is a hot loop.
    declare.mockRejectedValue(new CanopyPageStateRejected("too_large", "…"));
    renderHook(() => useCanopyPageState(BASE, SESSION, stateFor("a")));
    await waitFor(() => expect(declare).toHaveBeenCalledTimes(1));
    await new Promise((r) => setTimeout(r, 30));
    expect(declare).toHaveBeenCalledTimes(1);
  });

  it("re-declares for a different session rather than assuming it is current", async () => {
    // Switching chats must not let one session's bookkeeping make a brand new
    // session look already-declared.
    const { rerender } = renderHook(
      ({ id }) => useCanopyPageState(BASE, id, stateFor("a")),
      { initialProps: { id: "sess-1" } },
    );
    await waitFor(() => expect(declare).toHaveBeenCalledTimes(1));
    rerender({ id: "sess-2" });
    await waitFor(() => expect(declare).toHaveBeenCalledTimes(2));
    expect(declare).toHaveBeenLastCalledWith(BASE, "sess-2", stateFor("a"));
  });
});
