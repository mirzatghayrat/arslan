import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BrainNav from "./BrainNav";

vi.mock("./BrainIndexHealth", () => ({ default: () => <div /> }));
vi.mock("../../lib/feed", () => ({ feedFile: vi.fn(), feedTextOrUrl: vi.fn() }));

const branches = [
  { kind: "material", label: "材料", children: [
    { kind: "material", ref: "material:coll:1:okx.pdf", label: "okx.pdf", provenance: "投喂",
      confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 } ] },
  { kind: "learning", label: "心得", children: [] },
  { kind: "profile", label: "画像", children: [
    { kind: "profile", ref: "fact:1", label: "北京", provenance: "auto", category: "身份背景",
      confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 } ] },
  { kind: "note", label: "笔记", children: [
    { kind: "note", ref: "note:1", label: "报销单", provenance: "手写", tags: ["finance"],
      confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 } ] },
] as any;

describe("BrainNav", () => {
  const base = { branches, focusedId: null, onFocus: vi.fn(), onPick: vi.fn(), onChanged: vi.fn(),
    onTagFilter: vi.fn(), showTags: true, onToggleTags: vi.fn() };

  it("groups profile facts by category as a second level (once expanded)", () => {
    render(<BrainNav {...base} />);
    fireEvent.click(screen.getByText("画像"));   // categories start collapsed
    expect(screen.getByText("身份背景")).toBeTruthy();
  });

  it("shows a tag chip from note tags + fact category and filters on click", () => {
    const onTagFilter = vi.fn();
    render(<BrainNav {...base} onTagFilter={onTagFilter} />);
    fireEvent.click(screen.getByText("#finance"));
    expect(onTagFilter).toHaveBeenCalledWith("finance");
  });

  it("toggles tag-node visibility from the 标签 header", () => {
    const onToggleTags = vi.fn();
    render(<BrainNav {...base} onToggleTags={onToggleTags} />);
    fireEvent.click(screen.getByTitle("标签节点在图中显隐"));
    expect(onToggleTags).toHaveBeenCalled();
  });

  it("reveals a 新建 button on the 笔记 branch that creates a note", () => {
    const onCreateNote = vi.fn();
    render(<BrainNav {...base} onCreateNote={onCreateNote} />);
    fireEvent.click(screen.getByTitle("新建笔记"));
    expect(onCreateNote).toHaveBeenCalled();
  });
});
