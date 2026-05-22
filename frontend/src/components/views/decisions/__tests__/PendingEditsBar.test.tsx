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
});
