import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({ api: { createCollection: vi.fn().mockResolvedValue({ id: 1, name: "新建" }), ingestCollection: vi.fn(), listCollections: vi.fn().mockResolvedValue([]) } }));
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
});
