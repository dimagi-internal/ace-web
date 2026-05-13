import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useChatPaneCollapsed } from "./useChatPaneCollapsed";

const STORAGE_KEY = "ace.workbench.chatPaneCollapsed";

// jsdom in this vitest config doesn't ship a Storage shim. Install a
// minimal in-memory implementation per test so the hook's
// localStorage reads/writes behave like a real browser.
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

describe("useChatPaneCollapsed", () => {
  beforeEach(() => {
    installLocalStorageMock();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("defaults to collapsed=false when no stored value", () => {
    const { result } = renderHook(() => useChatPaneCollapsed());
    expect(result.current.collapsed).toBe(false);
  });

  it("reads the persisted '1' value on mount", () => {
    window.localStorage.setItem(STORAGE_KEY, "1");
    const { result } = renderHook(() => useChatPaneCollapsed());
    expect(result.current.collapsed).toBe(true);
  });

  it("toggle() flips the value and persists it", () => {
    const { result } = renderHook(() => useChatPaneCollapsed());

    act(() => result.current.toggle());
    expect(result.current.collapsed).toBe(true);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("1");

    act(() => result.current.toggle());
    expect(result.current.collapsed).toBe(false);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("0");
  });

  it("setCollapsed(true) persists '1'", () => {
    const { result } = renderHook(() => useChatPaneCollapsed());
    act(() => result.current.setCollapsed(true));
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe("1");
  });
});
