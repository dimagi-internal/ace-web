import { act, renderHook, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { useApi } from "./useApi"

describe("useApi", () => {
  it("starts in loading=true with data=null and resolves to the fetched value", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: 1 })
    const { result } = renderHook(() => useApi(fetcher, []))

    expect(result.current.loading).toBe(true)
    expect(result.current.data).toBeNull()

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data).toEqual({ ok: 1 })
    expect(result.current.error).toBeNull()
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it("captures rejection in error and resets data to null", async () => {
    const err = new Error("boom")
    const fetcher = vi.fn().mockRejectedValue(err)
    const { result } = renderHook(() => useApi(fetcher, []))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data).toBeNull()
    expect(result.current.error).toBe(err)
  })

  it("re-fires when deps change", async () => {
    const fetcher = vi.fn(async (n: number) => n * 2)
    let n = 1
    const { result, rerender } = renderHook(() => useApi(() => fetcher(n), [n]))

    await waitFor(() => expect(result.current.data).toBe(2))
    expect(fetcher).toHaveBeenCalledTimes(1)

    n = 5
    rerender()
    await waitFor(() => expect(result.current.data).toBe(10))
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it("skip=true does not fire the fetcher", async () => {
    const fetcher = vi.fn().mockResolvedValue("nope")
    const { result } = renderHook(() => useApi(fetcher, [], { skip: true }))

    // Synchronously: data null, loading false, fetcher not called.
    expect(result.current.data).toBeNull()
    expect(result.current.loading).toBe(false)
    expect(fetcher).not.toHaveBeenCalled()
  })

  it("ignores a stale resolution after deps change", async () => {
    // The first request resolves AFTER the second was launched.
    // Without cancellation, the stale result would clobber the fresh one.
    let resolveFirst: (v: string) => void = () => {}
    const firstPromise = new Promise<string>((res) => {
      resolveFirst = res
    })
    const fetcher = vi
      .fn<(n: number) => Promise<string>>()
      .mockImplementationOnce(() => firstPromise)
      .mockImplementationOnce(async () => "second")

    let n = 1
    const { result, rerender } = renderHook(() => useApi(() => fetcher(n), [n]))

    n = 2
    rerender()

    // Resolve the first (stale) request. The hook should ignore it.
    await act(async () => {
      resolveFirst("first-stale")
    })

    await waitFor(() => expect(result.current.data).toBe("second"))
    expect(result.current.data).not.toBe("first-stale")
  })
})
