import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({ api: {
  listSpawns: vi.fn().mockResolvedValue([]), listFacts: vi.fn().mockResolvedValue([]),
  listCollections: vi.fn().mockResolvedValue([{ id: 1, name: "保险资料", chunks: 6, sources: 1, spawn_ids: [] }]),
  getKnowledge: vi.fn().mockResolvedValue([]), getCollectionKnowledge: vi.fn().mockResolvedValue([{ source: "条款.pdf", chunks: 6 }]),
  createCollection: vi.fn(), ingestCollection: vi.fn(),
} }));
import BrainSection from "./BrainSection";

describe("BrainSection", () => {
  it("hovering a nav row highlights the matching sunburst branch (shared focusedId)", async () => {
    const { container } = render(<BrainSection />);
    await waitFor(() => expect(screen.getByText("保险资料")).toBeInTheDocument());
    fireEvent.mouseEnter(screen.getByText("保险资料"));
    await waitFor(() => expect(container.querySelector('path[data-node="coll:1"]')!.getAttribute("data-focus")).toBe("1"));
  });
});
