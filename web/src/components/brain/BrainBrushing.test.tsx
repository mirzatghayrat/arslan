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
        confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 }] },
    { kind: "profile", label: "画像", children: [
      { kind: "profile", ref: "fact:1", label: "北京", provenance: "auto", category: "身份背景",
        confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1,
        sensitive: true, superseded_by: 9 }] },
  ],
};
const GRAPH = {
  nodes: [
    { id: "note:1", ref: "note:1", kind: "note", label: "报销单", val: 1 },
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
  m.createNote.mockResolvedValue({ id: 7, title: "新的" });
});

describe("brain coordinated brushing", () => {
  it("🔴 hovering a node no longer destroys the tag filter", async () => {
    // The bug this splits apart: focusedId was the hover channel AND the tag filter, so
    // mouseleave -> null wiped the filter.
    //
    // 🔴 My first version of this test asserted the CHIP still had `is-active` after the
    // hover cycle — and it passed with the split reverted, because chip styling follows
    // the tagFilter state, which the bug does not touch. The bug destroys the filter's
    // EFFECT, so the assertion has to be about the effect: after hovering away, the graph
    // must still be dimmed to the tag's cluster (the profile fact is outside it).
    // Caught by mutation-testing this file, not by reading it.
    const dimOf = (kind: string) =>
      (document.querySelector(`[data-node][data-kind="${kind}"]`)!.parentElement as HTMLElement)
        .style.opacity;

    render(<BrainSection />);
    await screen.findByTestId("brain-graph");

    fireEvent.click(await screen.findByText(/#finance/));
    await waitFor(() => expect(dimOf("profile")).toBe("0.2"));   // filter is in effect

    const node = document.querySelector('[data-node][data-kind="note"]')!;
    fireEvent.mouseEnter(node);
    fireEvent.mouseLeave(node);

    // still in effect after the hover cycle — this is the assertion the bug fails
    await waitFor(() => expect(dimOf("profile")).toBe("0.2"));
    expect(screen.getByText(/#finance/).className).toContain("is-active");
  });

  it("offers an explicit way out of the filter, since mouseleave no longer clears it", async () => {
    render(<BrainSection />);
    await screen.findByTestId("brain-graph");
    fireEvent.click(await screen.findByText(/#finance/));

    const clear = await screen.findByTestId("clear-tag-filter");
    fireEvent.click(clear);
    await waitFor(() => expect(screen.queryByTestId("clear-tag-filter")).toBeNull());
    expect(screen.getByText(/#finance/).className).not.toContain("is-active");
  });

  it("🔴 hiding tag nodes drops the tag filter instead of blacking out the graph", async () => {
    // With tags hidden the tag node does not exist, so a surviving filter matches nothing
    // — and "matches nothing" would dim every node and edge with no explanation.
    render(<BrainSection />);
    await screen.findByTestId("brain-graph");
    fireEvent.click(await screen.findByText(/#finance/));
    expect(screen.getByText(/#finance/).className).toContain("is-active");

    fireEvent.click(screen.getByTitle("标签节点在图中显隐"));

    await waitFor(() => {
      const dimmed = [...document.querySelectorAll("[data-node]")].filter(
        (n) => (n.parentElement as HTMLElement).style.opacity === "0.2");
      expect(dimmed.length).toBe(0);
    });
  });

  it("hovering a tree row lights the matching graph node", async () => {
    render(<BrainSection />);
    await screen.findByTestId("brain-graph");
    fireEvent.click(await screen.findByText("笔记"));   // branches start collapsed
    const rows = await screen.findAllByTestId("brain-nav-row");
    const noteRow = rows.find((r) => r.textContent?.includes("报销单"))!;

    fireEvent.mouseEnter(noteRow);
    await waitFor(() => {
      const g = document.querySelector('[data-node][data-kind="note"]')!.parentElement!;
      expect(g.style.opacity).not.toBe("0.2");
      const other = document.querySelector('[data-node][data-kind="profile"]')!.parentElement!;
      expect(other.style.opacity).toBe("0.2");
    });
  });

  it("🔴 a new note appears in the graph — it used to fetch exactly once on mount", async () => {
    render(<BrainSection />);
    await screen.findByTestId("brain-graph");
    expect(m.getBrainGraph).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByTestId("new-note-input"), { target: { value: "新的" } });
    fireEvent.click(screen.getByTestId("new-note-btn"));

    await waitFor(() => expect(m.createNote).toHaveBeenCalledWith({ title: "新的" }));
    await waitFor(() => expect(m.getBrainGraph).toHaveBeenCalledTimes(2));
  });

  it("shows the sensitive and superseded markers the backend already sent", async () => {
    render(<BrainSection />);
    fireEvent.click(await screen.findByText("画像"));   // branches start collapsed
    fireEvent.click(await screen.findByText("身份背景"));
    const rows = await screen.findAllByTestId("brain-nav-row");
    const fact = rows.find((r) => r.textContent?.includes("北京"))!;
    expect(fact.querySelector('[data-testid="sensitive-badge"]')).toBeTruthy();
    expect(fact.textContent).toContain("已取代");
  });
});
