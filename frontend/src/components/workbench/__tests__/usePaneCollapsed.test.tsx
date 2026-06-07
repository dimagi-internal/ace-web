import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { usePaneCollapsed } from "../usePaneCollapsed";

// jsdom in this vitest config doesn't ship a Storage shim — install a
// minimal in-memory implementation per test (matches hooks/useChatPaneCollapsed.test.ts).
function installLocalStorageMock() {
  const store = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => (store.has(k) ? (store.get(k) as string) : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => Array.from(store.keys())[i] ?? null,
    get length() {
      return store.size;
    },
  });
}

describe("usePaneCollapsed", () => {
  beforeEach(() => installLocalStorageMock());
  afterEach(() => vi.unstubAllGlobals());

  it("defaults to false and toggles", () => {
    const { result } = renderHook(() => usePaneCollapsed("test.key"));
    expect(result.current.collapsed).toBe(false);
    act(() => result.current.toggle());
    expect(result.current.collapsed).toBe(true);
  });

  it("honors the defaultCollapsed argument when storage is empty", () => {
    const { result } = renderHook(() => usePaneCollapsed("test.key2", true));
    expect(result.current.collapsed).toBe(true);
  });

  it("persists to localStorage under the given key", () => {
    const { result } = renderHook(() => usePaneCollapsed("test.persist"));
    act(() => result.current.setCollapsed(true));
    expect(window.localStorage.getItem("test.persist")).toBe("1");
  });

  it("reads an existing stored value over the default", () => {
    window.localStorage.setItem("test.read", "1");
    const { result } = renderHook(() => usePaneCollapsed("test.read", false));
    expect(result.current.collapsed).toBe(true);
  });
});
