import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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
  it("renders the CSS glow orb, animated by default", () => {
    setReduced(false);
    const { container } = render(<BrainOrbCore />);
    const orb = container.querySelector(".brain-orb");
    expect(orb).not.toBeNull();
    expect(orb!.getAttribute("data-static")).toBe("0");
    expect(container.querySelectorAll(".brain-orb__blob").length).toBeGreaterThanOrEqual(3);
  });

  it("freezes to a static orb under reduced-motion", () => {
    setReduced(true);
    const { container } = render(<BrainOrbCore />);
    expect(container.querySelector(".brain-orb")!.getAttribute("data-static")).toBe("1");
  });

  it("respects the size prop", () => {
    setReduced(false);
    const { container } = render(<BrainOrbCore size={200} />);
    const orb = container.querySelector(".brain-orb") as HTMLElement;
    expect(orb.style.width).toBe("200px");
    expect(orb.style.height).toBe("200px");
  });
});
