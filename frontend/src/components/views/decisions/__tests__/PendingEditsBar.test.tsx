import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PendingEditsBar } from "../PendingEditsBar";

describe("PendingEditsBar", () => {
  it("renders nothing when count is 0", () => {
    const { container } = render(
      <PendingEditsBar count={0} onDiscardAll={vi.fn()} onForkAndRerun={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows pluralized count and the two action buttons", () => {
    render(<PendingEditsBar count={3} onDiscardAll={vi.fn()} onForkAndRerun={vi.fn()} />);
    expect(screen.getByText(/3 pending edits/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /discard/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /fork & re-run/i })).toBeInTheDocument();
  });

  it("singular form when count is 1", () => {
    render(<PendingEditsBar count={1} onDiscardAll={vi.fn()} onForkAndRerun={vi.fn()} />);
    expect(screen.getByText(/1 pending edit\b/i)).toBeInTheDocument();
  });

  it("clicking Discard all calls onDiscardAll", () => {
    const onDiscardAll = vi.fn();
    render(<PendingEditsBar count={1} onDiscardAll={onDiscardAll} onForkAndRerun={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /discard/i }));
    expect(onDiscardAll).toHaveBeenCalledTimes(1);
  });

  it("clicking Fork & re-run calls onForkAndRerun", () => {
    const onFork = vi.fn();
    render(<PendingEditsBar count={1} onDiscardAll={vi.fn()} onForkAndRerun={onFork} />);
    fireEvent.click(screen.getByRole("button", { name: /fork & re-run/i }));
    expect(onFork).toHaveBeenCalledTimes(1);
  });

  it("renders a Save to Drive button when onSaveToDrive is supplied — labelled honestly", () => {
    render(
      <PendingEditsBar
        count={2}
        onDiscardAll={vi.fn()}
        onForkAndRerun={vi.fn()}
        onSaveToDrive={vi.fn()}
      />,
    );
    // The file is inert until the ACE plugin learns to read it — the
    // label must say "Save to Drive", never "Apply to next run".
    expect(screen.getByRole("button", { name: /save to drive/i })).toBeInTheDocument();
    expect(screen.queryByText(/apply to next run/i)).toBeNull();
  });

  it("clicking Save to Drive calls onSaveToDrive", () => {
    const onSave = vi.fn();
    render(
      <PendingEditsBar
        count={1}
        onDiscardAll={vi.fn()}
        onForkAndRerun={vi.fn()}
        onSaveToDrive={onSave}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /save to drive/i }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("disables Save to Drive while a save is in flight", () => {
    const onSave = vi.fn();
    render(
      <PendingEditsBar
        count={1}
        onDiscardAll={vi.fn()}
        onForkAndRerun={vi.fn()}
        onSaveToDrive={onSave}
        saving
      />,
    );
    const btn = screen.getByRole("button", { name: /sav/i });
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("renders a quiet 'Export local copy' escape hatch when wired", () => {
    const onExport = vi.fn();
    render(
      <PendingEditsBar
        count={2}
        onDiscardAll={vi.fn()}
        onForkAndRerun={vi.fn()}
        onSaveToDrive={vi.fn()}
        onExportLocal={onExport}
      />,
    );
    const btn = screen.getByRole("button", { name: /export local copy/i });
    // Deliberately understated — a muted escape hatch, not a primary action.
    expect(btn.className).toMatch(/muted-foreground/);
    fireEvent.click(btn);
    expect(onExport).toHaveBeenCalledTimes(1);
  });

  it("omits Export local copy when no handler is wired", () => {
    render(
      <PendingEditsBar
        count={1}
        onDiscardAll={vi.fn()}
        onForkAndRerun={vi.fn()}
        onSaveToDrive={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /export local copy/i })).toBeNull();
  });

  it("omits Save to Drive when no handler is wired (legacy usage)", () => {
    render(<PendingEditsBar count={1} onDiscardAll={vi.fn()} onForkAndRerun={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /save to drive/i })).toBeNull();
  });
});
