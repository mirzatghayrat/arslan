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
    onTagFilter: vi.fn() };

  it("groups profile facts by category as a second level", () => {
    render(<BrainNav {...base} />);
    expect(screen.getByText("身份背景")).toBeTruthy();
  });

  it("shows a tag chip from note tags + fact category and filters on click", () => {
    const onTagFilter = vi.fn();
    render(<BrainNav {...base} onTagFilter={onTagFilter} />);
    fireEvent.click(screen.getByText("#finance"));
    expect(onTagFilter).toHaveBeenCalledWith("finance");
  });
});
