import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ArslanMark from "../components/brand/ArslanMark";

describe("ArslanMark", () => {
  it("renders an accessible svg labelled Arslan", () => {
    render(<ArslanMark />);
    const img = screen.getByRole("img", { name: "Arslan" });
    expect(img.tagName.toLowerCase()).toBe("svg");
  });

  it("includes the node-branch motif (a hub + three branch nodes = 4 circles, plus the head)", () => {
    const { container } = render(<ArslanMark />);
    // 1 head circle + 4 node circles
    expect(container.querySelectorAll("circle")).toHaveLength(5);
    // three branch edges
    expect(container.querySelectorAll("line")).toHaveLength(3);
  });

  it("applies a custom className for sizing", () => {
    const { container } = render(<ArslanMark className="h-10 w-10 text-brand" />);
    expect(container.querySelector("svg")?.getAttribute("class")).toContain("h-10");
  });
});
