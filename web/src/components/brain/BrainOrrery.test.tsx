import { render, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import BrainOrrery from "./BrainOrrery";
import type { BrainBranch } from "../../api/client";

const branches: BrainBranch[] = [
  { kind: "material", label: "材料", children: [
    { kind: "material", ref: "m1", label: "okx.pdf", provenance: "投喂", confidence: null,
      usage_count: 3, last_used_at: null, last_used_ref: null, value: 4 } ] },
  { kind: "learning", label: "心得", children: [] },
  { kind: "profile", label: "画像", children: [
    { kind: "profile", ref: "f1", label: "AE", provenance: "auto", confidence: 0.9,
      usage_count: 0, last_used_at: null, last_used_ref: null, value: 1 } ] },
];

describe("BrainOrrery star map", () => {
  it("renders three orbit rings, a dot per entry, and picks on click", () => {
    const onPick = vi.fn();
    const { container } = render(
      <BrainOrrery branches={branches} focusedId={null} onFocus={() => {}} onPick={onPick} />);
    // three orbit rings (fill=none circles)
    expect(container.querySelectorAll('circle[fill="none"]').length).toBe(3);
    // a dot carrying the material entry's title
    const dot = [...container.querySelectorAll("circle")]
      .find((c) => c.querySelector("title")?.textContent?.includes("okx.pdf"));
    expect(dot).toBeTruthy();
    fireEvent.click(dot!);
    expect(onPick).toHaveBeenCalled();
  });

  it("dims non-focused dots", () => {
    const { container } = render(
      <BrainOrrery branches={branches} focusedId="m1" onFocus={() => {}} onPick={() => {}} />);
    const other = [...container.querySelectorAll("circle")]
      .find((c) => c.querySelector("title")?.textContent?.includes("AE"));
    expect(other?.getAttribute("style")).toContain("0.25");
  });
});
