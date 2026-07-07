import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({ api: {
  listSpawns: vi.fn().mockResolvedValue([]), listFacts: vi.fn().mockResolvedValue([]),
  listCollections: vi.fn().mockResolvedValue([{ id: 1, name: "保险资料", chunks: 6, sources: 1, spawn_ids: [] }]),
  getKnowledge: vi.fn().mockResolvedValue([]), getCollectionKnowledge: vi.fn().mockResolvedValue([{ source: "条款.pdf", chunks: 6 }]),
  createCollection: vi.fn(), ingestCollection: vi.fn(),
} }));
vi.mock("../../lib/feed", () => ({ feedFile: vi.fn() }));
import BrainSection from "./BrainSection";

describe("BrainSection", () => {
  it("hovering a nav row highlights the matching sunburst branch (shared focusedId)", async () => {
    const { container } = render(<BrainSection />);
    await waitFor(() => expect(screen.getAllByText("保险资料").length).toBeGreaterThan(0));
    fireEvent.mouseEnter(screen.getByText("保险资料", { selector: "span" }));
    await waitFor(() => expect(container.querySelector('path[data-node="coll:1"]')!.getAttribute("data-dim")).toBe("0"));
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
