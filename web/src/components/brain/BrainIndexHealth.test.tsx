import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/client", () => ({
  api: { embeddingStatus: vi.fn(), reindexEmbeddings: vi.fn() },
}));

import BrainIndexHealth from "./BrainIndexHealth";
import { api } from "../../api/client";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
beforeEach(() => vi.clearAllMocks());

describe("BrainIndexHealth", () => {
  it("🔴 an empty corpus is not 100% — it has no percentage at all", async () => {
    // `total ? pct : 100` painted a FULL GREEN BAR for a brain with nothing indexed:
    // the most reassuring rendering of the least reassuring state. Asserting the strip
    // merely renders would pass under that bug, so assert the bar and the wording.
    m.embeddingStatus.mockResolvedValue({ model: "bge-small", embedded: 0, pending: 0 });
    render(<BrainIndexHealth />);
    expect((await screen.findByTestId("brain-health-meta")).textContent)
      .toContain("还没有可索引的内容");
    expect((document.querySelector(".brain-health__fill") as HTMLElement).style.width)
      .toBe("0%");
  });

  it("🔴 a failed status call says so instead of vanishing", async () => {
    // The strip used to return null on error — identical to "nothing to report".
    m.embeddingStatus.mockRejectedValue(new Error("boom"));
    render(<BrainIndexHealth />);
    const el = await screen.findByTestId("brain-health");
    expect(el.textContent).toContain("读不到索引状态");
    expect(el.textContent).toContain("不代表索引没问题");
  });

  it("says what pure-FTS costs when no embedding model is configured", async () => {
    m.embeddingStatus.mockResolvedValue({ model: null, embedded: 0, pending: 12 });
    render(<BrainIndexHealth />);
    expect((await screen.findByTestId("fts-note")).textContent).toContain("中文长词召回可能偏弱");
  });

  it("reports real progress when there is a corpus", async () => {
    m.embeddingStatus.mockResolvedValue({ model: "bge-small", embedded: 3, pending: 1 });
    render(<BrainIndexHealth />);
    expect((await screen.findByTestId("brain-health-meta")).textContent).toContain("已嵌入 3/4");
    expect((document.querySelector(".brain-health__fill") as HTMLElement).style.width).toBe("75%");
  });

  it("🔴 uses the real corpus size, not embedded+pending, as the denominator", async () => {
    // After a model switch `pending` counts stale rows that ALSO count as embedded, so
    // the old sum overshoots: 3 embedded + 3 pending on a 3-chunk corpus rendered 50%.
    // A test asserting only "a bar is drawn" would pass under that bug.
    m.embeddingStatus.mockResolvedValue({ model: "bge-large", embedded: 3, pending: 3, total: 3 });
    render(<BrainIndexHealth />);
    await screen.findByTestId("brain-health-meta");
    expect((document.querySelector(".brain-health__fill") as HTMLElement).style.width)
      .toBe("100%");
  });

  it("falls back to the old sum when an older backend omits total", async () => {
    m.embeddingStatus.mockResolvedValue({ model: "bge-small", embedded: 1, pending: 1 });
    render(<BrainIndexHealth />);
    await screen.findByTestId("brain-health-meta");
    expect((document.querySelector(".brain-health__fill") as HTMLElement).style.width)
      .toBe("50%");
  });
});
