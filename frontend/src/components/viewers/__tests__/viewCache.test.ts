import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearViewCache, loadView, MAX_CSV_ROWS, parseCsv } from "../viewCache";

function respond(body: BodyInit, type: string, init: ResponseInit = {}, headers: Record<string, string> = {}) {
  return new Response(body, {
    status: 200,
    ...init,
    headers: { "Content-Type": type, ...headers },
  });
}

const fetchMock = vi.fn();

beforeEach(() => {
  clearViewCache();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x") }));
});
afterEach(() => vi.unstubAllGlobals());

describe("loadView dispatches on the response's content type", () => {
  it("markdown, with the name and Drive link from the headers", async () => {
    fetchMock.mockResolvedValue(
      respond("# PDD", "text/markdown; charset=utf-8", {}, {
        "X-Artifact-Name": "PDD%20%E2%80%94%20v2.md",
        "X-Drive-Link": "https://drive/x",
      }),
    );
    expect(await loadView("/v/1")).toEqual({
      kind: "markdown", text: "# PDD", name: "PDD — v2.md", driveLink: "https://drive/x",
    });
  });

  it("csv becomes rows", async () => {
    fetchMock.mockResolvedValue(respond('a,b\n"x, y",2\n', "text/csv"));
    const r = await loadView("/v/2");
    expect(r.kind === "csv" && r.rows).toEqual([["a", "b"], ["x, y", "2"]]);
  });

  it("pdf, image and video become object URLs", async () => {
    fetchMock.mockResolvedValueOnce(respond("%PDF", "application/pdf"));
    fetchMock.mockResolvedValueOnce(respond("png", "image/png"));
    expect((await loadView("/v/pdf")).kind).toBe("pdf");
    expect((await loadView("/v/img")).kind).toBe("image");
  });

  it("anything else is text", async () => {
    fetchMock.mockResolvedValue(respond("key: value", "text/plain"));
    expect((await loadView("/v/3")).kind).toBe("text");
  });
});

describe("caching", () => {
  it("serves a warmed view without refetching", async () => {
    fetchMock.mockResolvedValue(respond("# x", "text/markdown"));
    await loadView("/v/a");
    await loadView("/v/a");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not cache a failure, so the next open retries", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ title: "Too large to show in the page" }), {
        status: 413,
        headers: { "Content-Type": "application/problem+json" },
      }),
    );
    const failed = await loadView("/v/b");
    expect(failed).toMatchObject({ kind: "error", status: 413, message: "Too large to show in the page" });
    fetchMock.mockResolvedValueOnce(respond("# ok", "text/markdown"));
    expect((await loadView("/v/b")).kind).toBe("markdown");
  });
});

describe("parseCsv", () => {
  it("handles quotes, doubled quotes and CRLF", () => {
    expect(parseCsv('a,"b ""q"""\r\n1,2')).toEqual([["a", 'b "q"'], ["1", "2"]]);
  });

  it("keeps a trailing empty field", () => {
    expect(parseCsv("a,\n")).toEqual([["a", ""]]);
  });
});

it("caps rendered rows", async () => {
  const body = Array.from({ length: MAX_CSV_ROWS + 5 }, (_, i) => `r${i}`).join("\n");
  fetchMock.mockResolvedValue(respond(body, "text/csv"));
  const r = await loadView("/v/big");
  expect(r.kind === "csv" && r.rows.length).toBe(MAX_CSV_ROWS);
  expect(r.kind === "csv" && r.truncated).toBe(true);
});

describe("loadView under load", () => {
  it("keeps at most 6 views in flight, queueing the rest", async () => {
    const pending: ((r: Response) => void)[] = [];
    fetchMock.mockImplementation(() => new Promise<Response>((resolve) => pending.push(resolve)));
    const loads = Array.from({ length: 10 }, (_, i) => loadView(`/v/q${i}`));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(6));
    pending.shift()!(respond("x", "text/plain"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(7));
    while (fetchMock.mock.calls.length < 10 || pending.length) {
      pending.shift()?.(respond("x", "text/plain"));
      await new Promise((r) => setTimeout(r, 0));
    }
    expect((await Promise.all(loads)).every((r) => r.kind === "text")).toBe(true);
  });

  it("retries a 503 after its Retry-After instead of giving up", async () => {
    vi.useFakeTimers();
    try {
      fetchMock
        .mockResolvedValueOnce(respond("{}", "application/problem+json", { status: 503 }, { "Retry-After": "1" }))
        .mockResolvedValueOnce(respond("# ok", "text/markdown"));
      const load = loadView("/v/busy");
      await vi.advanceTimersByTimeAsync(1000);
      expect(await load).toMatchObject({ kind: "markdown", text: "# ok" });
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("reports the 503 once the retries run out", async () => {
    vi.useFakeTimers();
    try {
      fetchMock.mockImplementation(() =>
        Promise.resolve(respond("{}", "application/problem+json", { status: 503 }, { "Retry-After": "1" })),
      );
      const load = loadView("/v/down");
      await vi.advanceTimersByTimeAsync(5000);
      expect(await load).toMatchObject({ kind: "error", status: 503 });
      expect(fetchMock).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });
});
