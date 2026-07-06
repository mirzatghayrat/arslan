import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({ api: { createCollection: vi.fn(), ingestCollection: vi.fn(), listCollections: vi.fn().mockResolvedValue([]) } }));
import KnowledgeNav from "./KnowledgeNav";
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
});
