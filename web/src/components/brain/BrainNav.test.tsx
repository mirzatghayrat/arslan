import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import BrainNav from "./BrainNav";

vi.mock("./BrainIndexHealth", () => ({ default: () => <div /> }));
vi.mock("../../lib/feed", () => ({ feedFile: vi.fn(), feedTextOrUrl: vi.fn() }));

// Shaped like what the backend NOW sends: stable keys, never display text.
// The fixture used to carry Chinese labels because the backend did, which is
// why nothing here noticed that an English interface was showing 材料 / 心得 /
// 画像 / 笔记. A fixture that does not resemble the wire cannot catch that.
const branches = [
  { kind: "material", label: "material", children: [
    { kind: "material", ref: "material:coll:1:okx.pdf", label: "okx.pdf", provenance: "fed",
      confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 } ] },
  { kind: "learning", label: "learning", children: [] },
  { kind: "profile", label: "profile", children: [
    { kind: "profile", ref: "fact:1", label: "甲城", provenance: "auto", category: "identity",
      confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 } ] },
  { kind: "note", label: "note", children: [
    { kind: "note", ref: "note:1", label: "报销单", provenance: "handwritten", tags: ["finance"],
      confidence: null, usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 } ] },
] as any;

describe("BrainNav", () => {
  const base = { branches, litId: null, onHover: vi.fn(), activeTag: null, onClearTag: vi.fn(), onPick: vi.fn(), onChanged: vi.fn(),
    onTagFilter: vi.fn(), showTags: true, onToggleTags: vi.fn() };

  it("groups profile facts by category as a second level (once expanded)", () => {
    render(<BrainNav {...base} />);
    fireEvent.click(screen.getByText("brain.kind_profile"));   // categories start collapsed
    expect(screen.getByText("brain.cat.identity")).toBeTruthy();
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
    fireEvent.click(screen.getByTitle("brain.tags_toggle_title"));
    expect(onToggleTags).toHaveBeenCalled();
  });
});
