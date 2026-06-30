import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AutoResizeTextarea } from "canopy-ui/ui";

describe("AutoResizeTextarea", () => {
  it("renders as a textbox", () => {
    render(<AutoResizeTextarea value="hello" onChange={vi.fn()} />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("displays the provided value", () => {
    render(<AutoResizeTextarea value="some content" onChange={vi.fn()} />);
    expect(screen.getByRole("textbox")).toHaveValue("some content");
  });

  it("calls onChange when the user types", () => {
    const onChange = vi.fn();
    render(<AutoResizeTextarea value="" onChange={onChange} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "typed text" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    // Verify the onChange handler received a React synthetic event object.
    const event = onChange.mock.calls[0][0] as React.ChangeEvent<HTMLTextAreaElement>;
    expect(event).toBeTruthy();
    expect(typeof event.target).toBe("object");
  });

  it("sets an explicit height once content is present (auto-fit on open)", () => {
    render(<AutoResizeTextarea value="some content" onChange={vi.fn()} />);
    const el = screen.getByRole("textbox") as HTMLTextAreaElement;
    // jsdom doesn't compute real scrollHeight, but the fit-once layout effect
    // runs for a non-empty value and pins `height` to `${scrollHeight}px`
    // (scrollHeight=0 in jsdom → "0px"). The assertion is that height was set.
    expect(el.style.height).toBeTruthy();
  });

  it("does NOT fit while the value is still empty (waits for content to load)", () => {
    render(<AutoResizeTextarea value="" onChange={vi.fn()} />);
    const el = screen.getByRole("textbox") as HTMLTextAreaElement;
    // Empty value on first paint (content not loaded yet) → no fit, height untouched.
    expect(el.style.height).toBe("");
  });

  it("does NOT have resize-none on the element", () => {
    render(<AutoResizeTextarea value="" onChange={vi.fn()} className="resize-none" />);
    const el = screen.getByRole("textbox");
    expect(el.className).not.toContain("resize-none");
  });

  it("has resize-y class for drag-resizable affordance", () => {
    render(<AutoResizeTextarea value="" onChange={vi.fn()} />);
    const el = screen.getByRole("textbox");
    expect(el.className).toContain("resize-y");
  });

  it("forwards extra className tokens alongside resize-y", () => {
    render(<AutoResizeTextarea value="" onChange={vi.fn()} className="font-mono text-sm" />);
    const el = screen.getByRole("textbox");
    expect(el.className).toContain("font-mono");
    expect(el.className).toContain("text-sm");
    expect(el.className).toContain("resize-y");
  });

  it("forwards id and aria-* props", () => {
    render(
      <AutoResizeTextarea
        id="my-textarea"
        aria-label="My label"
        value=""
        onChange={vi.fn()}
      />,
    );
    const el = screen.getByRole("textbox");
    expect(el.id).toBe("my-textarea");
    expect(el).toHaveAttribute("aria-label", "My label");
  });

  it("renders placeholder text", () => {
    render(<AutoResizeTextarea value="" onChange={vi.fn()} placeholder="Enter text…" />);
    expect(screen.getByRole("textbox")).toHaveAttribute("placeholder", "Enter text…");
  });

  it("forwards spellCheck={false}", () => {
    render(<AutoResizeTextarea value="" onChange={vi.fn()} spellCheck={false} />);
    // spellCheck=false → attribute spellcheck="false"
    expect(screen.getByRole("textbox")).toHaveAttribute("spellcheck", "false");
  });
});
