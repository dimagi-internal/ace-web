import { describe, expect, it, vi } from "vitest";

import { aceRuns, listActiveRuns, type ActiveRun } from "./api";

// `canopyJson` fetches a short-lived DelegatedToken first, through openapi-fetch
// with a RELATIVE url — which node cannot parse. Mocked so these tests exercise
// the mapping they are about rather than the auth hop, which token.test.ts owns.
vi.mock("./token", () => ({
  getCanopyToken: async () => "test-delegated-token",
  peekCanopyToken: () => "test-delegated-token",
}));

/**
 * The harness feed is the only place a runner-STARTED run appears — an inbound
 * email ringing the runner, a scheduled turn, a local emdash session. ace-web's
 * own session list is scoped to `source=ace-web` + this workspace's origin_key,
 * so none of those show up there, which is exactly why "find the active runs"
 * had nowhere to look.
 */

const row = (over: Record<string, unknown> = {}) => ({
  id: "11111111-1111-1111-1111-111111111111",
  emdash_task: "ace-kmc-metrics",
  project: "ace",
  agent: "ace",
  status: "in_progress",
  runner_name: "cloud-ec2-1",
  last_interacted_at: "2026-09-08T05:17:00Z",
  recent_messages: [{ role: "assistant", text: "first" }, { role: "assistant", text: "newest" }],
  ...over,
});

const run = (over: Partial<ActiveRun> = {}): ActiveRun => ({
  id: "a", task: "t", project: "ace", agent: "ace", runner_name: "cloud-ec2-1",
  status: "in_progress", last_interacted_at: null, latest_message: null, ...over,
});

describe("listActiveRuns", () => {
  it("maps the feed, taking the NEWEST message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([row()]), { status: 200 })));
    const [r] = await listActiveRuns("/canopy");
    expect(r.task).toBe("ace-kmc-metrics");
    expect(r.runner_name).toBe("cloud-ec2-1");
    // The tail is what tells you what a run is DOING; the first message would
    // be the oldest thing it ever said, which is the least useful line to show.
    expect(r.latest_message).toBe("newest");
    vi.unstubAllGlobals();
  });

  it("survives a session with no messages yet", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify([row({ recent_messages: [] })]), { status: 200 })));
    const [r] = await listActiveRuns("/canopy");
    expect(r.latest_message).toBeNull();
    vi.unstubAllGlobals();
  });
});

describe("aceRuns", () => {
  it("keeps ace's in-progress runs", () => {
    expect(aceRuns([run()])).toHaveLength(1);
  });

  it("drops finished runs", () => {
    expect(aceRuns([run({ status: "archived" })])).toHaveLength(0);
  });

  it("drops another agent's runs", () => {
    expect(aceRuns([run({ agent: "hal", project: "hal" })])).toHaveLength(0);
  });

  it("falls back to project only when the agent is unknown", () => {
    // Rows written before canopy-web #694 carry agent: null. They are still
    // ace's — `project` IS the agent's repo by convention — so they must show.
    expect(aceRuns([run({ agent: null, project: "ace" })])).toHaveLength(1);
  });

  it("does NOT let the fallback override a real agent", () => {
    // The dangerous shape: a checkout named "ace" whose work belongs to someone
    // else. Once the feed names an agent, that answer wins — the fallback is
    // for missing data, not a second opinion.
    expect(aceRuns([run({ agent: "hal", project: "ace" })])).toHaveLength(0);
  });

  it("ignores a repo checkout that is nobody's agent", () => {
    expect(aceRuns([run({ agent: null, project: "canopy-web" })])).toHaveLength(0);
  });
});
