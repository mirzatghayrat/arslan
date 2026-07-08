import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({ api: {
  getBrainTree: vi.fn().mockResolvedValue({ branches: [
    { kind: "material", label: "材料", children: [] },
    { kind: "learning", label: "心得", children: [] },
    { kind: "profile", label: "画像", children: [] },
    { kind: "note", label: "笔记", children: [] },
  ] }),
  getBrainEntry: vi.fn(),
  getBrainGraph: vi.fn().mockResolvedValue({ nodes: [{ id: "self", ref: "self", kind: "self", label: "你", val: 3 }], links: [] }),
  embeddingStatus: vi.fn().mockResolvedValue(null),
  createNote: vi.fn(),
  generateNotes: vi.fn(),
} }));
vi.mock("../../lib/feed", () => ({ feedFile: vi.fn(), feedTextOrUrl: vi.fn() }));
vi.mock("./BrainIndexHealth", () => ({ default: () => <div /> }));
import BrainSection from "./BrainSection";

describe("BrainSection", () => {
  it("defaults to the graph tab (full-height graph)", async () => {
    render(<BrainSection />);
    await waitFor(() => expect(screen.getByTestId("brain-graph")).toBeTruthy());
    expect(screen.getByText("图谱")).toBeTruthy();
    expect(screen.getByText("内容")).toBeTruthy();
  });

  it("switching to 内容 with nothing picked shows the empty hint", async () => {
    render(<BrainSection />);
    await waitFor(() => expect(screen.getByText("内容")).toBeTruthy());
    fireEvent.click(screen.getByText("内容"));
    expect(screen.getByText(/从左侧选一个条目/)).toBeTruthy();
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
