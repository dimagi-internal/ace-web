import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunProduct } from "@/api/types.ws";

import { ProductCard } from "../ProductCard";

const base: RunProduct = {
  id: "p:k", phase: "p", key: "k", kind: "connect_opportunity", title: "Bednet opp",
  subtitle: null, url: "https://connect.dimagi.com/a/o/opportunity/1/", file_id: null,
  facts: [], producer: null, chatbot: null,
};

describe("ProductCard", () => {
  it("says quietly when an output has neither an in-page view nor a screenshot", () => {
    render(<ProductCard product={base} />);
    expect(screen.getByText(/no screenshot yet/)).toBeInTheDocument();
  });

  it("says nothing for a Drive doc the page shows", () => {
    render(<ProductCard product={{ ...base, kind: "document", file_id: "f" }} />);
    expect(screen.queryByText(/no screenshot yet/)).not.toBeInTheDocument();
  });
});
