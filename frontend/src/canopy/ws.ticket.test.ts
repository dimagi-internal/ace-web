import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The socket opens with a one-time ticket, never the token: URLs land in access
 * logs, and a ticket found in one is already spent.
 */
const json = vi.fn();
let principal: "user" | "contact" = "user";
vi.mock("./client", () => ({ canopyRest: () => ({ json, raw: vi.fn() }) }));
vi.mock("./token", () => ({
  getCanopyToken: vi.fn().mockResolvedValue("secret-token"),
  peekCanopyToken: () => "secret-token",
  canopyPrincipal: () => principal,
}));

import { fetchCanopyWsUrl } from "./ws";

beforeEach(() => {
  json.mockReset().mockResolvedValue({ ticket: "tk-1", expires_in: 30 });
  principal = "user";
});

describe("fetchCanopyWsUrl", () => {
  it("puts a ticket on the URL and never the token", async () => {
    const url = await fetchCanopyWsUrl("https://canopy.dimagi.com", "s-1");
    expect(url).toBe("wss://canopy.dimagi.com/ws/canopy-sessions/s-1/?ticket=tk-1");
    expect(url).not.toContain("secret-token");
    expect(json).toHaveBeenCalledWith("/api/embed/ws-ticket", { method: "POST" });
  });

  it("a contact trades on the contact surface", async () => {
    principal = "contact";
    await fetchCanopyWsUrl("https://canopy.dimagi.com", "s-1");
    expect(json).toHaveBeenCalledWith("/api/contact/ws-ticket", { method: "POST" });
  });
});
