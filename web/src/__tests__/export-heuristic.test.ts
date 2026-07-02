/**
 * export-heuristic.test.ts — .md/.html exports contain the DELIVERABLE, not the
 * conversational preamble (user feedback: an exported report HTML began with
 * "I now have enough research data to compile… I will now generate the PPT").
 *
 * Rule under test (exportMarkdown): export starts at the FIRST markdown heading
 * line (# / ## / ###, fenced code ignored); leading lines are dropped. Fallbacks:
 * no heading → full text; stripping < 40% remaining → full text. Never empty.
 */

import { describe, it, expect } from "vitest";
import { exportMarkdown } from "../components/MessageBody";

describe("exportMarkdown — preamble stripping", () => {
  it("drops the conversational preamble before the first heading", () => {
    const text =
      "I now have enough research data to compile the report.\n" +
      "I will now generate the PPT using render_deck.\n" +
      "\n" +
      "# OKX 市场调研报告\n" +
      "\n" +
      "## 概览\n" +
      "正文内容。".repeat(30);
    const out = exportMarkdown(text);
    expect(out.startsWith("# OKX 市场调研报告")).toBe(true);
    expect(out).not.toContain("I now have enough research data");
  });

  it("supports ## and ### as the first heading", () => {
    const body = "详细内容。".repeat(40);
    for (const h of ["## 标题", "### 标题"]) {
      const out = exportMarkdown(`前言两句。\n${h}\n${body}`);
      expect(out.startsWith(h)).toBe(true);
    }
  });

  it("no heading → full text unchanged (never an empty export)", () => {
    const text = "Just a normal conversational reply with no headings at all.";
    expect(exportMarkdown(text)).toBe(text);
  });

  it("heading already on the first line → unchanged", () => {
    const text = "# Report\n\nBody text here.";
    expect(exportMarkdown(text)).toBe(text);
  });

  it("falls back to full text when stripping would leave < 40%", () => {
    // Long preamble, tiny headed tail — stripping would gut the export.
    const text = "很长的铺垫内容。".repeat(50) + "\n# 附注\n一行。";
    expect(exportMarkdown(text)).toBe(text);
  });

  it("ignores # lines inside fenced code blocks", () => {
    const text =
      "Preamble line.\n" +
      "```bash\n" +
      "# this is a shell comment, not a heading\n" +
      "```\n" +
      "# Real Title\n" +
      "Body. ".repeat(20);
    const out = exportMarkdown(text);
    expect(out.startsWith("# Real Title")).toBe(true);
    expect(out).not.toContain("Preamble line");
  });
});
