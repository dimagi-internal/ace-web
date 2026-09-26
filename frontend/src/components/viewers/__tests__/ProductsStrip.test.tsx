import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunProduct } from "@/api/types.ws";

import { ProductsStrip } from "../ProductsStrip";

function product(id: string, kind: RunProduct["kind"], title: string): RunProduct {
  return {
    id, phase: "p", key: id, kind, title, subtitle: null, url: "https://x", file_id: null,
    facts: [], producer: null, chatbot: null,
  };
}

const PRODUCTS = [
  product("pdd", "document", "Turmeric Market Survey"),
  product("learn", "commcare_app", "Turmeric — FLW Training"),
];

describe("ProductsStrip", () => {
  it("lists everything the run built outside a replay", () => {
    render(<ProductsStrip products={PRODUCTS} />);
    expect(screen.getByText("What this run built")).toBeInTheDocument();
    expect(screen.getByText("Turmeric Market Survey")).toBeInTheDocument();
  });

  it("in a replay, hides an unbuilt product's name behind its kind", () => {
    render(<ProductsStrip products={PRODUCTS} isRevealed={(p) => p.id === "pdd"} />);
    expect(screen.getByText("Built so far · 1/2")).toBeInTheDocument();
    expect(screen.queryByText("Turmeric — FLW Training")).not.toBeInTheDocument();
    const placeholder = screen.getByRole("button", { name: /CommCare app/ });
    expect(placeholder).toBeDisabled();
  });

  it("renders nothing for a run with no products", () => {
    const { container } = render(<ProductsStrip products={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
