import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({ api: {
  createCollection: vi.fn().mockResolvedValue({ id: 1, name: "新建" }),
  ingestCollection: vi.fn(),
  listCollections: vi.fn().mockResolvedValue([]),
  deleteCollection: vi.fn().mockResolvedValue({ deleted: true }),
  patchCollection: vi.fn().mockResolvedValue({ id: 1, name: "改名" }),
  deleteCollectionSource: vi.fn().mockResolvedValue({ deleted: true }),
} }));
import KnowledgeNav from "./KnowledgeNav";
import { api } from "../../api/client";
import type { TreeNode } from "../../hooks/useKnowledgeTree";

const tree: TreeNode = {
  id: "root", name: "YOU", kind: "root", cat: "collection", value: 9, children: [
    { id: "cat:collection", name: "共享库", kind: "category", cat: "collection", value: 9, children: [
      { id: "coll:1", name: "保险资料", kind: "collection", cat: "collection", value: 9, children: [
        { id: "src:coll:1:条款", name: "条款.pdf", kind: "source", cat: "collection", value: 9 }] }] },
    { id: "cat:spawn", name: "分身深井", kind: "category", cat: "spawn", value: 0, children: [] },
    { id: "cat:pref", name: "偏好", kind: "category", cat: "pref", value: 0, children: [] },
  ],
};

const treeWithColl: TreeNode = {
  id: "root", name: "YOU", kind: "root", cat: "collection", value: 0, children: [
    { id: "cat:collection", name: "共享库", kind: "category", cat: "collection", value: 0, children: [
      { id: "coll:5", name: "我的资料", kind: "collection", cat: "collection", value: 0, children: [] }] },
    { id: "cat:spawn", name: "分身深井", kind: "category", cat: "spawn", value: 0, children: [] },
    { id: "cat:pref", name: "偏好", kind: "category", cat: "pref", value: 0, children: [] },
  ],
};

describe("KnowledgeNav", () => {
  it("renders the tree and fires onFocus on row hover", () => {
    const onFocus = vi.fn();
    render(<KnowledgeNav tree={tree} focusedId={null} onFocus={onFocus} onChanged={() => {}} />);
    const row = screen.getByText("保险资料");
    fireEvent.mouseEnter(row);
    expect(onFocus).toHaveBeenCalledWith("coll:1");
  });

  it("frontend-filters the tree by search text", () => {
    render(<KnowledgeNav tree={tree} focusedId={null} onFocus={() => {}} onChanged={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: "条款" } });
    expect(screen.getByText("条款.pdf")).toBeInTheDocument();
    expect(screen.queryByText("偏好")).not.toBeInTheDocument();
  });

  it("collapses deep nodes and expands on click", () => {
    render(<KnowledgeNav tree={tree} focusedId={null} onFocus={() => {}} onChanged={() => {}} />);
    // a source nested under a collection group is hidden until the group is expanded
    expect(screen.queryByText("条款.pdf")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("保险资料"));
    expect(screen.getByText("条款.pdf")).toBeInTheDocument();
  });

  it("auto-expands the path to a search hit", () => {
    render(<KnowledgeNav tree={tree} focusedId={null} onFocus={() => {}} onChanged={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: "条款" } });
    expect(screen.getByText("条款.pdf")).toBeInTheDocument();
  });

  it("paste box feeds via bucketing (not a raw 快速收集 collection)", async () => {
    const feed = await import("../../lib/feed");
    const spy = vi.spyOn(feed, "feedTextOrUrl").mockResolvedValue({ chunks_added: 1 } as any);
    render(<KnowledgeNav tree={tree} focusedId={null} onFocus={() => {}} onChanged={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText(/快速投喂/), { target: { value: "https://x.com" } });
    fireEvent.click(screen.getByText(/投喂到共享库/));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("https://x.com"));
  });

  it("＋ 新建库 creates a named collection", async () => {
    render(<KnowledgeNav tree={tree} focusedId={null} onFocus={() => {}} onChanged={() => {}} />);
    fireEvent.click(screen.getByText(/新建库/));
    fireEvent.change(screen.getByPlaceholderText(/库名/), { target: { value: "我的资料" } });
    fireEvent.click(screen.getByText(/建立/));
    await waitFor(() => expect(api.createCollection).toHaveBeenCalledWith("我的资料"));
  });

  it("dropping a file on a collection row feeds into that collection", async () => {
    const feed = await import("../../lib/feed");
    const spy = vi.spyOn(feed, "feedFileInto").mockResolvedValue({ chunks_added: 1 } as any);
    render(<KnowledgeNav tree={treeWithColl} focusedId={null} onFocus={() => {}} onChanged={() => {}} />);
    const row = screen.getByText("我的资料").closest("[data-coll-id]") as HTMLElement;
    const file = new File(["x"], "a.pdf");
    fireEvent.drop(row, { dataTransfer: { files: [file], types: ["Files"] } });
    await waitFor(() => expect(spy).toHaveBeenCalledWith(5, expect.any(File)));
  });

  it("disables 投喂到共享库 while the input is empty (no more silent no-op)", () => {
    render(<KnowledgeNav tree={tree} focusedId={null} onFocus={() => {}} onChanged={() => {}} />);
    const btn = screen.getByText(/投喂到共享库/).closest("button")!;
    expect(btn).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/快速投喂/), { target: { value: "hello" } });
    expect(btn).not.toBeDisabled();
  });

  it("the ＋ file button feeds picked files via feedFile (auto-bucket)", async () => {
    const feed = await import("../../lib/feed");
    const spy = vi.spyOn(feed, "feedFile").mockResolvedValue({ chunks_added: 1 } as any);
    const { container } = render(<KnowledgeNav tree={tree} focusedId={null} onFocus={() => {}} onChanged={() => {}} />);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [new File(["x"], "doc.pdf")] } });
    await waitFor(() => expect(spy).toHaveBeenCalledWith(expect.any(File)));
  });

  it("collection row exposes rename → patchCollection with the new name", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("新名字");
    render(<KnowledgeNav tree={tree} focusedId="coll:1" onFocus={() => {}} onChanged={() => {}} />);
    fireEvent.click(screen.getByTitle("重命名库"));
    await waitFor(() => expect(api.patchCollection).toHaveBeenCalledWith(1, { name: "新名字" }));
  });

  it("collection row exposes delete → deleteCollection after confirm", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<KnowledgeNav tree={tree} focusedId="coll:1" onFocus={() => {}} onChanged={() => {}} />);
    fireEvent.click(screen.getByTitle("删除整个库"));
    await waitFor(() => expect(api.deleteCollection).toHaveBeenCalledWith(1));
  });

  it("collection SOURCE leaf exposes delete → deleteCollectionSource(collId, source)", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<KnowledgeNav tree={tree} focusedId="src:coll:1:条款" onFocus={() => {}} onChanged={() => {}} />);
    fireEvent.click(screen.getByText("保险资料"));            // expand the parent collection
    fireEvent.click(screen.getByTitle("删除此来源"));
    await waitFor(() => expect(api.deleteCollectionSource).toHaveBeenCalledWith(1, "条款.pdf"));
  });

  it("does NOT offer delete/rename on spawn-well or preference rows (different backend)", () => {
    const t2: TreeNode = {
      id: "root", name: "YOU", kind: "root", cat: "collection", value: 1, children: [
        { id: "cat:spawn", name: "分身深井", kind: "category", cat: "spawn", value: 1, children: [
          { id: "dom:research", name: "research", kind: "category", cat: "spawn", value: 1, children: [
            { id: "spawn:7", name: "小美", kind: "spawn", cat: "spawn", value: 1, children: [] }] }] },
      ],
    };
    render(<KnowledgeNav tree={t2} focusedId="spawn:7" onFocus={() => {}} onChanged={() => {}} />);
    expect(screen.queryByTitle("删除整个库")).toBeNull();
    expect(screen.queryByTitle("重命名库")).toBeNull();
  });
});
