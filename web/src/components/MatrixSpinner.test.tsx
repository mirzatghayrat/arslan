import { render } from "@testing-library/react";
import { describe, test, expect } from "vitest";
import MatrixSpinner from "./MatrixSpinner";

describe("MatrixSpinner", () => {
  test("renders the default ring of 8 animated dots", () => {
    const { container } = render(<MatrixSpinner />);
    const svg = container.querySelector("svg.matrix-spinner");
    expect(svg).not.toBeNull();
    const dots = container.querySelectorAll("circle.matrix-spinner__dot");
    expect(dots.length).toBe(8);
  });

  test("staggers each dot's animation-delay so the pulse chases around the ring", () => {
    const { container } = render(<MatrixSpinner count={4} />);
    const delays = Array.from(
      container.querySelectorAll<SVGCircleElement>("circle.matrix-spinner__dot"),
    ).map((c) => c.style.animationDelay);
    // 4 dots over a 1s cycle → 0s, 0.25s, 0.5s, 0.75s (all distinct).
    expect(new Set(delays).size).toBe(4);
  });

  test("honours size and tints via currentColor (className passthrough)", () => {
    const { container } = render(
      <MatrixSpinner size={20} className="text-primary" label="Loading" />,
    );
    const svg = container.querySelector("svg.matrix-spinner")!;
    expect(svg.getAttribute("width")).toBe("20");
    expect(svg.getAttribute("fill")).toBe("currentColor");
    expect(svg.getAttribute("aria-label")).toBe("Loading");
    expect(svg.classList.contains("text-primary")).toBe(true);
  });
});
