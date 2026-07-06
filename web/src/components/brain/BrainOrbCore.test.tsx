import { fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../backgrounds/Orb", () => ({ default: () => <div data-testid="live-orb" /> }));
let mode = "dark";
vi.mock("../../stores/themeStore", () => ({ useThemeStore: (sel: any) => sel({ mode }) }));

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

afterEach(() => {
  mode = "dark";
});

describe("BrainOrbCore", () => {
  it("dark mode plays the dark video (no live WebGL)", () => {
    setReduced(false);
    mode = "dark";
    const { container, queryByTestId } = render(<BrainOrbCore />);
    expect(container.querySelector("video")!.getAttribute("src")).toBe("/orb-dark.mp4");
    expect(queryByTestId("live-orb")).toBeNull();
  });

  it("light mode plays the light video", () => {
    setReduced(false);
    mode = "light";
    const { container } = render(<BrainOrbCore />);
    expect(container.querySelector("video")!.getAttribute("src")).toBe("/orb-light.mp4");
  });

  it("reduced-motion renders a static core (no video, no live orb)", () => {
    setReduced(true);
    const { container, queryByTestId } = render(<BrainOrbCore />);
    expect(container.querySelector("video")).toBeNull();
    expect(queryByTestId("live-orb")).toBeNull();
    expect(container.querySelector('[data-static-core="1"]')).not.toBeNull();
  });

  it("falls back to the live orb when the video errors", () => {
    setReduced(false);
    mode = "dark";
    const { container, getByTestId } = render(<BrainOrbCore />);
    fireEvent.error(container.querySelector("video")!);
    expect(getByTestId("live-orb")).not.toBeNull();
  });
});
