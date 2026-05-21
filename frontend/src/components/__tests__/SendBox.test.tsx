import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { SendBox } from "../SendBox";
import type { Draft } from "../../api/types.ws";

/**
 * Build a Draft owned by ``currentUserId`` so canEdit=true unconditionally
 * (we want to isolate the CLI-state gate).
 */
function buildDraft(currentUserId: number): Draft {
  return {
    id: 1,
    slot: "next",
    status: "open",
    body: "hello",
    version: 1,
    last_editor: currentUserId,
    last_edit_at: new Date().toISOString(),
  };
}

function renderSendBox(
  cliProps: { cliHasBlob: boolean | null; cliAuthenticated: boolean | null },
) {
  const currentUserId = 42;
  return render(
    <MemoryRouter>
      <SendBox
        draft={buildDraft(currentUserId)}
        currentUserId={currentUserId}
        holderIsPresent={true}
        isStreaming={false}
        streamingMessageId={null}
        onUpdate={vi.fn()}
        onSend={vi.fn()}
        onStop={vi.fn()}
        onTakeOver={vi.fn()}
        {...cliProps}
      />
    </MemoryRouter>,
  );
}

describe("SendBox CLI auth gating (issue #479)", () => {
  it("blob present + live check passing — send enabled, no warning", () => {
    renderSendBox({ cliHasBlob: true, cliAuthenticated: true });
    const sendButton = screen.getByRole("button", { name: /send/i });
    expect(sendButton).toBeEnabled();
    expect(screen.queryByText(/live check failed/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/no claude cli credentials uploaded/i),
    ).not.toBeInTheDocument();
  });

  it("blob present + live check FAILING — send STILL enabled, warning chip visible", () => {
    // This is the cold-start case from issue #479: the blob is fine but
    // the live check timed out. The UI must NOT block the user; let the
    // chat surface real auth errors at the right time + place.
    renderSendBox({ cliHasBlob: true, cliAuthenticated: false });
    const sendButton = screen.getByRole("button", { name: /send/i });
    expect(sendButton).toBeEnabled();
    expect(screen.getByText(/live check failed/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/no claude cli credentials uploaded/i),
    ).not.toBeInTheDocument();
  });

  it("no blob — send disabled with clear 'no credentials' message", () => {
    renderSendBox({ cliHasBlob: false, cliAuthenticated: false });
    const sendButton = screen.getByRole("button", { name: /send/i });
    expect(sendButton).toBeDisabled();
    expect(
      screen.getByText(/no claude cli credentials uploaded/i),
    ).toBeInTheDocument();
  });

  it("loading state (both null) — send enabled, no warning, no blocker", () => {
    // null = still loading. Don't gate sends on a poll we haven't seen
    // yet; the textarea was filled in before the first poll came back.
    renderSendBox({ cliHasBlob: null, cliAuthenticated: null });
    const sendButton = screen.getByRole("button", { name: /send/i });
    expect(sendButton).toBeEnabled();
    expect(screen.queryByText(/live check failed/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/no claude cli credentials uploaded/i),
    ).not.toBeInTheDocument();
  });

  it("warning chip is suppressed when sends are blocked outright", () => {
    // If there's no blob at all the live-check warning would be noise on
    // top of the more important "no credentials uploaded" blocker.
    renderSendBox({ cliHasBlob: false, cliAuthenticated: false });
    expect(screen.queryByText(/live check failed/i)).not.toBeInTheDocument();
  });
});
