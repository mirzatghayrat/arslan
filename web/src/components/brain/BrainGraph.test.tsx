import { fireEvent, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { graph } = vi.hoisted(() => ({
  graph: {
    nodes: [
      { id: "self", ref: "self", kind: "self", label: "你", val: 9 },
      { id: "note:1", ref: "note:1", kind: "note", label: "报销单", val: 3 },
      { id: "tag:finance", ref: "tag:finance", kind: "tag", label: "finance", val: 1 },
      { id: "ghost:未来想法", ref: "ghost:未来想法", kind: "ghost", label: "未来想法", val: 0.5 },
    ],
    links: [
      { source: "note:1", target: "tag:finance", type: "tag" },
      { source: "self", target: "tag:finance", type: "hub" },
      { source: "note:1", target: "ghost:未来想法", type: "link" },
    ],
  },
}));
vi.mock("../../api/client", () => ({ api: { getBrainGraph: vi.fn().mockResolvedValue(graph) } }));

import BrainGraph from "./BrainGraph";

describe("BrainGraph", () => {
  const noop = () => {};
  it("renders self / tag / ghost node kinds", async () => {
    const { container } = render(
      <BrainGraph litId={null} onHover={noop} onPick={noop} onCreateNoteWithTitle={noop} showTags />);
    await waitFor(() => expect(container.querySelector('[data-kind="self"]')).toBeTruthy());
    expect(container.querySelector('[data-kind="tag"]')).toBeTruthy();
    expect(container.querySelector('[data-kind="ghost"]')).toBeTruthy();
  });

  it("double-clicking a ghost node asks to create that note", async () => {
    const onCreate = vi.fn();
    const { container } = render(
      <BrainGraph litId={null} onHover={noop} onPick={noop} onCreateNoteWithTitle={onCreate} showTags />);
    await waitFor(() => expect(container.querySelector('[data-kind="ghost"]')).toBeTruthy());
    fireEvent.doubleClick(container.querySelector('[data-kind="ghost"]')!);
    expect(onCreate).toHaveBeenCalledWith("未来想法");
  });
});
