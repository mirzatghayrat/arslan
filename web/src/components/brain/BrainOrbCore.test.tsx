import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../backgrounds/Strands", () => ({ default: () => <div data-testid="strands" /> }));

import BrainOrbCore from "./BrainOrbCore";

function setReduced(v: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (q: string) => ({
      matches: v && q.includes("reduced"),
      media: q,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      onchange: null,
      dispatchEvent: () => false,
    }),
  });
}

describe("BrainOrbCore", () => {
  it("renders the strands orb", () => {
    setReduced(false);
    const { container, getByTestId } = render(<BrainOrbCore />);
    expect(container.querySelector('[data-orb-strands="1"]')).not.toBeNull();
    expect(getByTestId("strands")).not.toBeNull();
  });

  it("respects size", () => {
    setReduced(false);
    const { container } = render(<BrainOrbCore size={200} />);
    expect((container.querySelector('[data-orb-strands="1"]') as HTMLElement).style.width).toBe("200px");
  });

  it("freezes under reduced-motion (no breathe animation)", () => {
    setReduced(true);
    const { container } = render(<BrainOrbCore />);
    expect((container.querySelector('[data-orb-strands="1"]') as HTMLElement).style.animation).toBe("none");
  });
});
