import { render } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
vi.mock("../../api/client", () => ({ api: { getBrainGraph: vi.fn().mockResolvedValue({
  nodes: [
    { id: "note:1", ref: "note:1", kind: "note", label: "A", val: 1 },
    { id: "note:2", ref: "note:2", kind: "note", label: "B", val: 1 },
    { id: "ghost:X", ref: "ghost:X", kind: "ghost", label: "X", val: 0.5 },
  ],
  links: [{ source: "note:1", target: "note:2", type: "link" }, { source: "note:2", target: "ghost:X", type: "link" }],
}) } }));
import BrainGraph from "./BrainGraph";

describe("BrainGraph", () => {
  it("renders a node circle per node and a line per link", async () => {
    const { container, findByTestId } = render(
      <BrainGraph focusedId={null} onFocus={() => {}} onPick={() => {}} />);
    await findByTestId("brain-graph");
    // wait a tick for the fetch+sim setup
    await new Promise((r) => setTimeout(r, 50));
    expect(container.querySelectorAll("circle[data-node]").length).toBe(3);
    expect(container.querySelectorAll("line[data-link]").length).toBe(2);
    expect(container.querySelector('circle[data-kind="ghost"]')).toBeTruthy();
  });
});
