import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({ api: {
  getBrainTree: vi.fn().mockResolvedValue({ branches: [
    { kind: "material", label: "材料", children: [] },
    { kind: "learning", label: "心得", children: [] },
    { kind: "profile", label: "画像", children: [
      { kind: "profile", ref: "fact:1", label: "北京", provenance: "auto", category: "身份背景",
        confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 } ] },
    { kind: "note", label: "笔记", children: [] },
  ] }),
  getBrainEntry: vi.fn().mockResolvedValue({ kind: "profile", ref: "fact:1", label: "北京",
    provenance: "auto", excerpt: "在北京工作", usage_count: 0, last_used_at: null, last_used_ref: null }),
  getBrainGraph: vi.fn().mockResolvedValue({ nodes: [{ id: "self", ref: "self", kind: "self", label: "你", val: 3 }], links: [] }),
  embeddingStatus: vi.fn().mockResolvedValue(null),
  // F0: the activity strip and the undo affordance are new callers. This mock is NOT a
  // partial of the real api object, so any method the subtree touches must be listed or
  // it is `undefined` at runtime and the whole render throws.
  getBrainUsageEvents: vi.fn().mockResolvedValue({
    covered_kinds: ["material", "learning", "note"],
    coverage_note: "covers material / learning / note only",
    window_start: null, applied_limit: 5000, truncated: false, events: [],
  }),
  undoSupersede: vi.fn(),
  getNote: vi.fn().mockResolvedValue({ id: 1, title: "n", content: "", tags: [], backlinks: [] }),
  createNote: vi.fn(),
  generateNotes: vi.fn(),
} }));
vi.mock("../../lib/feed", () => ({ feedFile: vi.fn(), feedTextOrUrl: vi.fn() }));
vi.mock("./BrainIndexHealth", () => ({ default: () => <div /> }));
import BrainSection from "./BrainSection";

describe("BrainSection", () => {
  it("always mounts the graph as the main canvas (no tabs)", async () => {
    render(<BrainSection />);
    await waitFor(() => expect(screen.getByTestId("brain-graph")).toBeTruthy());
    expect(screen.queryByText("内容")).toBeNull();   // the graph/content tabs are gone
  });

  it("clicking a tree row opens its detail rail while the graph stays mounted", async () => {
    render(<BrainSection />);
    fireEvent.click(await screen.findByText("画像"));      // every level starts collapsed…
    fireEvent.click(await screen.findByText("身份背景"));   // …expand the category then its sub-group
    const row = await screen.findByTestId("brain-nav-row");
    fireEvent.click(row);
    await waitFor(() => expect(screen.getByText("在北京工作")).toBeTruthy());  // detail rail excerpt
    expect(screen.getByTestId("brain-graph")).toBeTruthy();                    // graph still there
  });

  it("feeds dropped files then refreshes", async () => {
    const feed = await import("../../lib/feed");
    const spy = vi.spyOn(feed, "feedFile").mockResolvedValue({ chunks_added: 1 } as any);
    const { container } = render(<BrainSection />);
    const zone = container.querySelector('[data-dropzone="1"]')! as HTMLElement;
    const file = new File(["x"], "a.pdf", { type: "application/pdf" });
    fireEvent.drop(zone, { dataTransfer: { files: [file], types: ["Files"] } });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
  });
});
