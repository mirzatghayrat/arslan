import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import KnowledgeOrrery from "./KnowledgeOrrery";

const nodes = [
  { id: "hub", cat: "hub" as const, label: "YOU" },
  { id: "s1", cat: "spawn" as const, label: "小红书营销" },
  { id: "src1", cat: "source" as const, label: "brand.pdf" },
  { id: "p1", cat: "pref" as const, label: "偏口语" },
];
const edges = [{ a: "hub", b: "s1" }, { a: "s1", b: "src1" }, { a: "hub", b: "p1" }];

describe("KnowledgeOrrery", () => {
  it("mounts with data and renders a canvas without throwing", () => {
    const { container } = render(<KnowledgeOrrery nodes={nodes} edges={edges} />);
    expect(container.querySelector("canvas")).not.toBeNull();
  });
  it("mounts with empty data (hub-only) without throwing", () => {
    const { container } = render(<KnowledgeOrrery nodes={[{ id: "hub", cat: "hub", label: "YOU" }]} edges={[]} />);
    expect(container.querySelector("canvas")).not.toBeNull();
  });
  it("unmounts cleanly", () => {
    const { unmount } = render(<KnowledgeOrrery nodes={nodes} edges={edges} />);
    expect(() => unmount()).not.toThrow();
  });
});
