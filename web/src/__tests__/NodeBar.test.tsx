import { render } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import "../i18n";
import NodeBar from "../components/arslan/NodeBar";
import { NODE_SEQUENCES, patternFor } from "../components/arslan/nodeBarSequences";

describe("nodeBarSequences (ported from make_arslan_node_bar_gif.py)", () => {
  it("thinking sequence matches the script verbatim", () => {
    expect(NODE_SEQUENCES.thinking).toEqual([
      ["o", "on", "o"],
      ["o", "o", "o"],
      ["o", "on", "o"],
      ["on", "on", "on"],
      ["o", "on", "o"],
      ["on", "on", "on"],
    ]);
  });

  it("done is a single all-active frame", () => {
    expect(NODE_SEQUENCES.done).toEqual([["on", "on", "on"]]);
  });

  it("waiting_confirmation cycles a length-4 sequence", () => {
    expect(NODE_SEQUENCES.waiting_confirmation).toHaveLength(4);
  });

  it("patternFor wraps the frame index modulo the sequence length", () => {
    // thinking has 6 frames; frame 3 -> all active, frame 9 -> same as frame 3
    expect(patternFor("thinking", 3)).toEqual(["on", "on", "on"]);
    expect(patternFor("thinking", 9)).toEqual(["on", "on", "on"]);
    // done has 1 frame; any index -> all active
    expect(patternFor("done", 7)).toEqual(["on", "on", "on"]);
  });
});

describe("NodeBar component", () => {
  beforeEach(() => {
    // default: motion allowed
    window.matchMedia = vi.fn().mockImplementation((q: string) => ({
      matches: false,
      media: q,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })) as unknown as typeof window.matchMedia;
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders three nodes and two connecting edges as SVG", () => {
    const { container } = render(<NodeBar state="thinking" />);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.querySelectorAll("circle")).toHaveLength(3);
    expect(container.querySelectorAll("line")).toHaveLength(2);
  });

  it("renders the static 'done' frame with all three nodes active", () => {
    const { container } = render(<NodeBar state="done" />);
    const circles = Array.from(container.querySelectorAll("circle"));
    // all three filled with the brand orange
    for (const c of circles) {
      expect(c.getAttribute("fill")).toBe("#FF8E24");
    }
  });

  it("under reduced motion renders a static frame (no animation interval)", () => {
    window.matchMedia = vi.fn().mockImplementation((q: string) => ({
      matches: true, // prefers-reduced-motion: reduce
      media: q,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })) as unknown as typeof window.matchMedia;
    const setInterval = vi.spyOn(window, "setInterval");
    render(<NodeBar state="thinking" />);
    expect(setInterval).not.toHaveBeenCalled();
  });
});
