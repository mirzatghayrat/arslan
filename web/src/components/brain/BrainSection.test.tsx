import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({ api: {
  listSpawns: vi.fn().mockResolvedValue([]), listFacts: vi.fn().mockResolvedValue([]),
  listCollections: vi.fn().mockResolvedValue([{ id: 1, name: "保险资料", chunks: 6, sources: 1, spawn_ids: [] }]),
  getKnowledge: vi.fn().mockResolvedValue([]), getCollectionKnowledge: vi.fn().mockResolvedValue([{ source: "条款.pdf", chunks: 6 }]),
  createCollection: vi.fn(), ingestCollection: vi.fn(),
  getBrainTree: vi.fn().mockResolvedValue({ branches: [
    { kind: "material", label: "材料", children: [
      { kind: "material", ref: "material:coll:1:okx.pdf", label: "okx.pdf", provenance: "投喂",
        confidence: null, usage_count: 3, last_used_at: null, last_used_ref: null, value: 4 } ] },
    { kind: "learning", label: "心得", children: [] },
    { kind: "profile", label: "画像", children: [] },
  ] }),
  getBrainEntry: vi.fn(),
} }));
vi.mock("../../lib/feed", () => ({ feedFile: vi.fn() }));
import BrainSection from "./BrainSection";

describe("BrainSection (A′)", () => {
  it("renders the three brain panels driven by /brain/tree", async () => {
    render(<BrainSection />);
    await waitFor(() => expect(screen.getByText("okx.pdf")).toBeInTheDocument());
    // labels appear in both the panel headers and the sunburst titles → use getAllByText
    expect(screen.getAllByText("材料").length).toBeGreaterThan(0);
    expect(screen.getAllByText("心得").length).toBeGreaterThan(0);
    expect(screen.getAllByText("画像").length).toBeGreaterThan(0);
    expect(screen.getByText(/用过 3/)).toBeInTheDocument();
  });

  it("drops files → feeds each via feedFile then refreshes", async () => {
    const feed = await import("../../lib/feed");
    const spy = vi.spyOn(feed, "feedFile").mockResolvedValue({ chunks_added: 1 } as any);
    const { container } = render(<BrainSection />);
    const zone = container.querySelector('[data-dropzone="1"]')! as HTMLElement;
    const file = new File(["x"], "a.pdf", { type: "application/pdf" });
    fireEvent.dragOver(zone, { dataTransfer: { files: [file], types: ["Files"] } });
    expect(container.querySelector('[data-drop-overlay="1"]')).not.toBeNull(); // overlay shows
    fireEvent.drop(zone, { dataTransfer: { files: [file], types: ["Files"] } });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
  });
});
