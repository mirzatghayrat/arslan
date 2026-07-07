import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BrainPanels from "./BrainPanels";
import type { BrainBranch } from "../../api/client";

const branches: BrainBranch[] = [
  { kind: "material", label: "材料", children: [
    { kind: "material", ref: "material:coll:1:okx.pdf", label: "okx.pdf",
      provenance: "投喂", confidence: null, usage_count: 8, last_used_at: null, last_used_ref: null, value: 9 } ] },
  { kind: "learning", label: "心得", children: [] },
  { kind: "profile", label: "画像", children: [
    { kind: "profile", ref: "fact:1", label: "Acme AE",
      provenance: "auto", confidence: 0.95, usage_count: 6, last_used_at: null, last_used_ref: null, value: 7 } ] },
];

describe("BrainPanels", () => {
  it("renders three type panels with usage counts", () => {
    render(<BrainPanels branches={branches} onPick={() => {}} />);
    expect(screen.getByText("材料")).toBeInTheDocument();
    expect(screen.getByText("心得")).toBeInTheDocument();
    expect(screen.getByText("画像")).toBeInTheDocument();
    expect(screen.getByText("okx.pdf")).toBeInTheDocument();
    expect(screen.getByText(/用过 8/)).toBeInTheDocument();
  });

  it("shows an empty state for a branch with no entries", () => {
    render(<BrainPanels branches={branches} onPick={() => {}} />);
    expect(screen.getByText("暂无")).toBeInTheDocument();
  });
});
