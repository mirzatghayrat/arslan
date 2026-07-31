import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../api/client", () => ({ api: {
  getRunCatalog: vi.fn().mockResolvedValue({ range: "1h",
    fleet: { run_count: 8, error_ratio: 0.12, p95_ms: 18600, pass_rate: 78, tokens_sum: 48000 },
    spawns: [
      { spawn_id: 1, spawn_name: "Bad", model: "qwen", run_count: 5, error_ratio: 0.2, p95_ms: 31400, pass_rate: 40, avg_score: 5.2, tokens_sum: 3100, health: "red", score_trend: [6,5,5.2], latency_trend: [30000,31000,31400], error_trend: [0.1,0.15,0.2], rate_trend: [1,2,2] },
      { spawn_id: 2, spawn_name: "Good", model: "gpt", run_count: 3, error_ratio: 0, p95_ms: 6000, pass_rate: 100, avg_score: 8.1, tokens_sum: 2300, health: "green", score_trend: [8,8.1], latency_trend: [5000,5500,6000], error_trend: [0,0,0], rate_trend: [1,1,1] },
    ] }),
  getRunAnomalies: vi.fn().mockResolvedValue([]),
  getRunVitals: vi.fn().mockResolvedValue({
    range: "1h", bucket_ms: 120000, total: 0, error_ratio: 0, p95_ms: null,
    buckets: [], duration_bins: [], duration_matrix: [],
  }),
  getRunTimeline: vi.fn().mockResolvedValue({ range: "1h", buckets: [], spawns: [] }),
} }));
import DiagnosisCatalog from "../components/DiagnosisCatalog";

describe("DiagnosisCatalog", () => {
  it("renders RED fleet cards and a worst-first spawn table", async () => {
    render(<DiagnosisCatalog onClose={() => {}} onSelectSpawn={() => {}} />);
    expect(await screen.findByText("Bad")).toBeTruthy();
    const rows = screen.getAllByTestId("cat-row");
    expect(rows[0].textContent).toContain("Bad");
    expect(screen.getByText(/12%/)).toBeTruthy();      // fleet error ratio
  });
  it("switching range refetches", async () => {
    const { api } = await import("../api/client");
    render(<DiagnosisCatalog onClose={() => {}} onSelectSpawn={() => {}} />);
    await screen.findByText("Bad");
    fireEvent.click(screen.getByText("diag.range_24h"));
    await waitFor(() => expect(api.getRunCatalog).toHaveBeenCalledWith("24h"));
  });
  it("clicking a spawn row calls onSelectSpawn", async () => {
    const onSel = vi.fn();
    render(<DiagnosisCatalog onClose={() => {}} onSelectSpawn={onSel} />);
    fireEvent.click((await screen.findByText("Bad")).closest("[data-testid='cat-row']")!);
    expect(onSel).toHaveBeenCalledWith(1, "Bad");
  });
  it("anomaly badge is collapsed by default and expands on click", async () => {
    const { api } = await import("../api/client");
    // Shaped like the wire NOW: keys + params, never an assembled sentence.
    // The fixture used to carry Chinese titles because the server sent them —
    // which is exactly why nothing here noticed that an English interface was
    // being shown Chinese.
    (api.getRunAnomalies as any).mockResolvedValueOnce([
      { severity:"red", kind:"error_rate", spawn_id:1, spawn_name:"Bad",
        title_key:"anomaly.error_rate.high", detail_key:"anomaly.error_rate.detail",
        params:{ pct:20, errs:1, n:5 }, since:null, run_id:null },
      { severity:"amber", kind:"tool_error", spawn_id:3, spawn_name:"CI",
        title_key:"anomaly.tool_error.title", detail_key:"anomaly.tool_error.detail",
        params:{ tool:"web_extract", run_id:58 }, since:null, run_id:58 },
    ]);
    render(<DiagnosisCatalog onClose={() => {}} onSelectSpawn={() => {}} />);
    const badge = await screen.findByTestId("anomaly-badge");
    expect(badge.textContent).toContain("diag.anomalies_n")  // mocked t drops interpolation; the real count is in the key params;                    // count while collapsed
    expect(screen.queryByText("anomaly.error_rate.high")).toBeNull();   // hidden by default
    fireEvent.click(badge);
    expect(screen.getByText("anomaly.error_rate.high")).toBeTruthy();   // expanded shows it
  });
  it("renders spawn cards (not a table) when narrow", async () => {
    render(<DiagnosisCatalog onClose={() => {}} onSelectSpawn={() => {}} narrow />);
    expect((await screen.findAllByTestId("cat-card")).length).toBeGreaterThan(0); // cards, not cat-row
    expect(screen.queryByTestId("cat-row")).toBeNull();           // table rows gone in narrow
  });
  it("renders per-row line sparklines for rate/error/latency trends", async () => {
    render(<DiagnosisCatalog onClose={() => {}} onSelectSpawn={() => {}} />);
    const rows = await screen.findAllByTestId("cat-row");
    const firstRowSparks = rows[0].querySelectorAll("[data-testid='line-spark']");
    expect(firstRowSparks.length).toBeGreaterThanOrEqual(3);
  });
});
