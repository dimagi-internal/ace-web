import { describe, expect, it, vi } from "vitest";

import { listActiveTurns, liveTurns, listTurnEvents, type ActiveTurn } from "./api";

vi.mock("./token", () => ({
  getCanopyToken: async () => "test-delegated-token",
  peekCanopyToken: () => "test-delegated-token",
}));

/**
 * Turns are the only place a CLOUD run exists.
 *
 * `/api/harness/sessions` is derived from emdash's sqlite. The cloud runner has
 * no emdash — it spawns `claude -p` headless and reports `sessions=[]` on every
 * heartbeat — so an inbound-email run, which the routing rules deliberately pin
 * to that box, appears in that feed NEVER. It does stream a full event ledger
 * (184 events on a real email turn, measured 2026-09-08), which is what these
 * read.
 */

const turnRow = (over: Record<string, unknown> = {}) => ({
  id: "aaaaaaaa-1111-2222-3333-444444444444",
  agent_slug: "ace",
  project: "",
  origin: "email",
  status: "running",
  prompt: "/ace:turn --thread 1a0812c440895bb7",
  claimed_by_name: "cloud-ec2-1",
  created_at: "2026-09-08T13:23:14Z",
  session_id: "",
  ...over,
});

const turn = (over: Partial<ActiveTurn> = {}): ActiveTurn => ({
  id: "a", agent: "ace", project: "", origin: "email", status: "running",
  prompt: "p", runner_name: "cloud-ec2-1", created_at: "", session_id: "", ...over,
});

describe("listActiveTurns", () => {
  it("maps a cloud email turn", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify([turnRow()]), { status: 200 })));
    const [t] = await listActiveTurns("/canopy");
    expect(t.origin).toBe("email");
    expect(t.runner_name).toBe("cloud-ec2-1");
    expect(t.agent).toBe("ace");
    vi.unstubAllGlobals();
  });

  it("asks for the agent's turns without pinning a status", async () => {
    // Filtering to `running` on the wire would hide a turn still QUEUED behind a
    // strict routing rule — i.e. exactly while someone waits for their email to
    // be picked up, the list would say nothing is happening.
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (u: unknown) => {
      urls.push(String(u));
      return new Response("[]", { status: 200 });
    }));
    await listActiveTurns("/canopy", "ace");
    expect(urls[0]).toContain("agent=ace");
    expect(urls[0]).not.toContain("status=");
    vi.unstubAllGlobals();
  });
});

describe("liveTurns", () => {
  it("keeps a running cloud email turn — THE regression", () => {
    expect(liveTurns([turn()])).toHaveLength(1);
  });

  it("keeps a queued turn: waiting for the cloud box is still 'happening'", () => {
    expect(liveTurns([turn({ status: "queued" })])).toHaveLength(1);
  });

  it("drops a finished turn", () => {
    expect(liveTurns([turn({ status: "done" })])).toHaveLength(0);
  });

  it("drops a turn already shown as a session, so laptop runs are not doubled", () => {
    const sid = "809d4900-6fd7-48c8-b370-50594badd489";
    expect(liveTurns([turn({ session_id: sid })], [sid])).toHaveLength(0);
  });

  it("keeps a session-driving turn whose session is NOT listed", () => {
    // The sessions feed is scoped and can legitimately omit it; dropping the
    // turn too would lose the run from both halves at once.
    expect(liveTurns([turn({ session_id: "not-in-the-list" })], ["other"])).toHaveLength(1);
  });
});

describe("listTurnEvents", () => {
  it("pages by seq rather than re-fetching from zero", async () => {
    // The server caps a response at 500 rows, so re-reading from 0 would both
    // truncate a long run and cost more the longer it ran.
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (u: unknown) => {
      urls.push(String(u));
      return new Response(
        JSON.stringify({ events: [{ seq: 7, ts: "", kind: "assistant", payload: {} }] }),
        { status: 200 });
    }));
    const events = await listTurnEvents("/canopy", "t1", 6);
    expect(urls[0]).toContain("after=6");
    expect(events[0]!.seq).toBe(7);
    vi.unstubAllGlobals();
  });

  it("survives a turn with no events yet", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
    expect(await listTurnEvents("/canopy", "t1")).toEqual([]);
    vi.unstubAllGlobals();
  });
});
