import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import FilterChips from "../components/FilterChips";

describe("FilterChips", () => {
  const chips = [
    { id: "all", label: "All", count: 5 },
    { id: "a", label: "Alpha", count: 3 },
    { id: "b", label: "Beta" },
  ];

  it("renders every chip with its count badge (no badge when count is omitted)", () => {
    render(<FilterChips chips={chips} active="all" onSelect={() => {}} />);
    expect(screen.getByRole("button", { name: /All\s*5/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Alpha\s*3/ })).toBeInTheDocument();
    // Beta has no count → label only, no trailing number
    expect(screen.getByRole("button", { name: "Beta" })).toBeInTheDocument();
  });

  it("marks the active chip with aria-pressed", () => {
    render(<FilterChips chips={chips} active="a" onSelect={() => {}} />);
    expect(screen.getByRole("button", { name: /Alpha/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /All/ })).toHaveAttribute("aria-pressed", "false");
  });

  it("clicking a chip calls onSelect with its id", () => {
    const onSelect = vi.fn();
    render(<FilterChips chips={chips} active="all" onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /Alpha/ }));
    expect(onSelect).toHaveBeenCalledWith("a");
  });
});
