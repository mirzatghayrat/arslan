import { describe, it, expect } from "vitest";
import { lineDiff } from "../lib/lineDiff";

describe("lineDiff", () => {
  it("marks identical text entirely as same", () => {
    const rows = lineDiff("a\nb\nc", "a\nb\nc");
    expect(rows.every((r) => r.type === "same")).toBe(true);
    expect(rows.map((r) => r.text)).toEqual(["a", "b", "c"]);
  });

  it("emits del then add for a changed line", () => {
    const rows = lineDiff("a\nOLD\nc", "a\nNEW\nc");
    expect(rows).toEqual([
      { type: "same", text: "a" },
      { type: "del", text: "OLD" },
      { type: "add", text: "NEW" },
      { type: "same", text: "c" },
    ]);
  });

  it("detects a pure insertion", () => {
    const rows = lineDiff("a\nc", "a\nb\nc");
    expect(rows).toEqual([
      { type: "same", text: "a" },
      { type: "add", text: "b" },
      { type: "same", text: "c" },
    ]);
  });

  it("detects a pure deletion", () => {
    const rows = lineDiff("a\nb\nc", "a\nc");
    expect(rows).toEqual([
      { type: "same", text: "a" },
      { type: "del", text: "b" },
      { type: "same", text: "c" },
    ]);
  });

  it("handles empty base (all added)", () => {
    const rows = lineDiff("", "x\ny");
    // "" splits to [""] so the empty first line is 'same' with the empty candidate line…
    expect(rows.some((r) => r.type === "add" && r.text === "x")).toBe(true);
    expect(rows.some((r) => r.type === "add" && r.text === "y")).toBe(true);
  });

  it("preserves reading order across multiple hunks", () => {
    const base = "keep1\ndrop\nkeep2";
    const cand = "keep1\nkeep2\nnew";
    const rows = lineDiff(base, cand);
    expect(rows.map((r) => `${r.type}:${r.text}`)).toEqual([
      "same:keep1",
      "del:drop",
      "same:keep2",
      "add:new",
    ]);
  });
});
