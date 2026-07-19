import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({
  api: {
    getBrainTree: vi.fn(),
    getBrainGraph: vi.fn(),
    getBrainEntry: vi.fn(),
    getBrainUsageEvents: vi.fn(),
    getNote: vi.fn(),
    createNote: vi.fn(),
    generateNotes: vi.fn(),
    embeddingStatus: vi.fn().mockResolvedValue(null),
    undoSupersede: vi.fn(),
  },
}));
vi.mock("../../lib/feed", () => ({ feedFile: vi.fn(), feedTextOrUrl: vi.fn() }));
vi.mock("./BrainIndexHealth", () => ({ default: () => <div /> }));

import BrainSection from "./BrainSection";
import { api } from "../../api/client";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const TREE = {
  branches: [
    { kind: "note", label: "笔记", children: [
      { kind: "note", ref: "note:1", label: "报销单", provenance: "手写", tags: ["finance"],
        confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 },
      { kind: "note", ref: "note:2", label: "别的", provenance: "手写", tags: [],
        confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 }] },
    { kind: "profile", label: "画像", children: [
      { kind: "profile", ref: "fact:1", label: "北京", provenance: "auto", category: "身份背景",
        confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 }] },
  ],
};
const GRAPH = {
  nodes: [
    { id: "note:1", ref: "note:1", kind: "note", label: "报销单", val: 1 },
    { id: "note:2", ref: "note:2", kind: "note", label: "别的", val: 1 },
    { id: "tag:finance", ref: "tag:finance", kind: "tag", label: "finance", val: 1 },
    { id: "fact:1", ref: "fact:1", kind: "profile", label: "北京", val: 1 },
  ],
  links: [{ source: "note:1", target: "tag:finance", type: "tag" }],
};

beforeEach(() => {
  vi.clearAllMocks();
  m.getBrainTree.mockResolvedValue(TREE);
  m.getBrainGraph.mockResolvedValue(GRAPH);
  m.getBrainUsageEvents.mockResolvedValue({
    covered_kinds: ["material", "learning", "note"], coverage_note: "note",
    window_start: null, applied_limit: 5000, truncated: false, events: [],
  });
  m.getNote.mockImplementation(async (id: number) =>
    id === 1
      ? { id: 1, title: "报销单", content: "", tags: ["finance"], backlinks: [{ id: 2, title: "别的" }] }
      : { id: 2, title: "别的", content: "", tags: [], backlinks: [] });
});

const opacityOf = (sel: string) =>
  (document.querySelector(sel)!.parentElement as HTMLElement).style.opacity;

describe("repro: backlink click strands hoveredId", () => {
  it("tag filter effect after hovering+clicking a backlink", async () => {
    render(<BrainSection />);
    await screen.findByTestId("brain-graph");

    // 1. turn on the tag filter
    fireEvent.click(await screen.findByText(/#finance/));
    await waitFor(() =>
      expect(opacityOf('[data-node][data-kind="profile"]')).toBe("0.2"));

    // 2. open note 1 from the tree
    fireEvent.click(await screen.findByText("笔记"));
    const rows = await screen.findAllByTestId("brain-nav-row");
    const noteRow = rows.find((r) => r.textContent?.includes("报销单"))!;
    fireEvent.click(noteRow);
    const backlink = await screen.findByTestId("backlink");

    // 3. hover it, then CLICK it (no mouseleave — the button unmounts under the cursor)
    fireEvent.mouseEnter(backlink);
    fireEvent.click(backlink);

    await waitFor(() => expect(screen.getByDisplayValue("别的")).toBeTruthy());

    // what does the graph show now?
    const state = {
      chipActive: screen.getByText(/#finance/).className.includes("is-active"),
      note1: opacityOf('[data-node][data-kind="note"]'),
      profile: opacityOf('[data-node][data-kind="profile"]'),
      tag: opacityOf('[data-node][data-kind="tag"]'),
      backlinkStillMounted: !!screen.queryByTestId("backlink"),
    };
    // eslint-disable-next-line no-console
    console.log("STATE", JSON.stringify(state));
    expect(state).toBeTruthy();
  });
});
