/**
 * Activity › Usage dashboard (0.1.50): numbers first, then three rows on one time
 * axis (tokens, duration heatmap, outcome), then the per-model list.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k), i18n: { language: "en" } }),
}));
const { BANDS, bin } = vi.hoisted(() => ({
  BANDS: ["<10s", "10–30s", "30s–1m", "1–3m", "3–10m", ">10m"],
  bin: (i: number, runs: number, failed: number, tokens: number, durations: number[]) =>
    ({ start_ts: 1_790_000_000 + i * 3600, runs, failed, tokens_total: tokens, durations }),
}));
vi.mock("../api/client", () => ({
  api: {
    getUsageSummary: vi.fn().mockResolvedValue({
      range: "7d", daily: [], not_covered: [],
      rows: [{ provider: "openai", model: "deepseek-v4-pro", scope: "answer", tokens_total: 120000, usd: 0.42, estimated_any: false },
             { provider: null, model: null, scope: "answer", tokens_total: 0, usd: null, estimated_any: false }],
      tokens_total: 120000, usd_total: 0.42, estimated_any: false,
      runs: { total: 13, done: 10, failed: 3, stopped: 0, running: 0, p50_ms: 41000, p95_ms: 177000 },
      bin_seconds: 3600, duration_bands: BANDS,
      bins: [bin(0, 2, 0, 5000, [1, 1, 0, 0, 0, 0]), bin(1, 0, 0, 0, [0, 0, 0, 0, 0, 0]), bin(2, 3, 1, 9000, [0, 0, 1, 2, 0, 0])],
    }),
  },
}));
import UsageCard from "../components/UsageCard";

describe("Usage dashboard", () => {
  it("leads with the five numbers", async () => {
    render(<UsageCard />);
    const kpis = await screen.findByTestId("usage-kpis");
    await within(kpis).findByText("13");
    expect(kpis.textContent).toContain("77%");          // 10 of 13 finished
    expect(kpis.textContent).toContain("2m 57s");       // p95
    expect(kpis.textContent).toContain("41s");          // median
    expect(kpis.textContent).toContain("120k");
    expect(kpis.textContent).toContain("$0.42");
    expect(kpis.textContent).not.toContain("≈");
  });

  it("draws a heatmap of duration bands × slices, longest band on top", async () => {
    render(<UsageCard />);
    const heat = await screen.findByTestId("usage-heatmap");
    const rows = Array.from(heat.children);
    expect(rows).toHaveLength(BANDS.length);
    expect(rows[0].textContent).toContain(">10m");
    expect(rows[rows.length - 1].textContent).toContain("<10s");
    const cells = rows.map(r => r.querySelectorAll("[title]").length);
    expect(new Set(cells)).toEqual(new Set([3]));
    // the 1–3m row's busiest cell (2 runs) is the strongest tint
    const busiest = rows[2].querySelectorAll<HTMLElement>("[title]")[2];
    expect(busiest.style.background).toContain("100%");
  });

  it("marks each slice's outcome: failed red, ok green, idle neither", async () => {
    render(<UsageCard />);
    const cells = (await screen.findByTestId("usage-outcomes")).querySelectorAll<HTMLElement>("[title]");
    expect(cells[0].className).toContain("bg-success");
    expect(cells[1].className).not.toMatch(/bg-(success|danger)/);
    expect(cells[2].className).toContain("bg-danger");
  });
});

describe("Usage dashboard model list", () => {
  it("hides model lines with no tokens; the totals still count everything", async () => {
    render(<UsageCard />);
    await screen.findByText("deepseek-v4-pro");
    expect(screen.getAllByTestId("usage-row")).toHaveLength(1);
    expect(screen.getByTestId("usage-kpis").textContent).toContain("120k");
  });
});
