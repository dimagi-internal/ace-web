import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DefaultTenancyPanel, tenancyPatch } from "./DefaultTenancyPanel";

const SHARED = {
  hq_domain: "connect-ace-prod",
  connect_holding_org: "ace-nm-org",
  labs_allowed_domains: ["@dimagi.com", "@dimagi-ai.com"],
};

describe("tenancyPatch", () => {
  it("sends only changed fields, and blank clears", () => {
    expect(
      tenancyPatch(SHARED, {
        hq_domain: "connect-ace-prod",
        connect_pm_org: "ace-pm-org",
        connect_holding_org: "",
        labs_allowed_domains: "@dimagi.com, @dimagi-ai.com",
      }),
    ).toEqual({ connect_pm_org: "ace-pm-org", connect_holding_org: null });
  });

  it("splits Labs domains on commas and spaces", () => {
    expect(
      tenancyPatch(SHARED, {
        hq_domain: "connect-ace-prod",
        connect_pm_org: "",
        connect_holding_org: "ace-nm-org",
        labs_allowed_domains: "@sparkmicrogrants.org  @dimagi.com",
      }),
    ).toEqual({ labs_allowed_domains: ["@sparkmicrogrants.org", "@dimagi.com"] });
  });
});

describe("DefaultTenancyPanel", () => {
  it("is read-only for non-owners and shows unset fields", () => {
    render(<DefaultTenancyPanel tenancy={SHARED} canEdit={false} onSave={vi.fn()} />);
    expect(screen.getByText("connect-ace-prod")).toBeTruthy();
    expect(screen.getByText("not set")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("saves the patch for an owner", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<DefaultTenancyPanel tenancy={SHARED} canEdit onSave={onSave} />);
    fireEvent.change(screen.getByLabelText("Connect program-manager org"), {
      target: { value: "ace-pm-org" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ connect_pm_org: "ace-pm-org" }));
    expect(await screen.findByText(/existing opps are unchanged/)).toBeTruthy();
  });

  it("does not call save when nothing changed", async () => {
    const onSave = vi.fn();
    render(<DefaultTenancyPanel tenancy={SHARED} canEdit onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("No changes.")).toBeTruthy();
    expect(onSave).not.toHaveBeenCalled();
  });
});
