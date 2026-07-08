import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({ api: {
  getBrainTree: vi.fn().mockResolvedValue({ branches: [
    { kind: "material", label: "材料", children: [
      { kind: "material", ref: "material:coll:1:okx.pdf", label: "okx.pdf", provenance: "投喂",
        confidence: null, usage_count: 3, last_used_at: null, last_used_ref: null, value: 4 } ] },
    { kind: "learning", label: "心得", children: [] },
    { kind: "profile", label: "画像", children: [] },
  ] }),
  getBrainEntry: vi.fn(),
  getBrainGraph: vi.fn().mockResolvedValue({ nodes: [], links: [] }),
  embeddingStatus: vi.fn().mockResolvedValue(null),
} }));
vi.mock("../../lib/feed", () => ({ feedFile: vi.fn(), feedTextOrUrl: vi.fn() }));
import BrainSection from "./BrainSection";

describe("BrainSection (integrated)", () => {
  it("drives left nav + panels + orrery from one /brain/tree", async () => {
    render(<BrainSection />);
    // okx.pdf now appears in both the nav row and the panel → getAllByText
    await waitFor(() => expect(screen.getAllByText("okx.pdf").length).toBeGreaterThan(0));
    expect(screen.getAllByText("材料").length).toBeGreaterThan(0);
    expect(screen.getAllByText("心得").length).toBeGreaterThan(0);
    expect(screen.getAllByText("画像").length).toBeGreaterThan(0);
    // the unified left nav renders a synced row
    expect(screen.getAllByTestId("brain-nav-row").length).toBeGreaterThan(0);
    // the force graph replaces the orrery
    expect(screen.getByTestId("brain-graph")).toBeTruthy();
  });

  it("drops files → feeds each via feedFile then refreshes", async () => {
    const feed = await import("../../lib/feed");
    const spy = vi.spyOn(feed, "feedFile").mockResolvedValue({ chunks_added: 1 } as any);
    const { container } = render(<BrainSection />);
    const zone = container.querySelector('[data-dropzone="1"]')! as HTMLElement;
    const file = new File(["x"], "a.pdf", { type: "application/pdf" });
    fireEvent.dragOver(zone, { dataTransfer: { files: [file], types: ["Files"] } });
    expect(container.querySelector('[data-drop-overlay="1"]')).not.toBeNull();
    fireEvent.drop(zone, { dataTransfer: { files: [file], types: ["Files"] } });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
  });
});
