import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../api/client", () => ({ api: {
  getRunCatalog: vi.fn().mockResolvedValue({ range:"1h", fleet:{run_count:2,error_ratio:0,p95_ms:1000,pass_rate:100,tokens_sum:10},
    spawns:[{spawn_id:1,spawn_name:"Bad",model:"m",run_count:2,error_ratio:0,p95_ms:1000,pass_rate:100,avg_score:8,tokens_sum:10,health:"green",score_trend:[8]}] }),
  getRunAnomalies: vi.fn().mockResolvedValue([]),
  getRuns: vi.fn().mockResolvedValue([]),
  getRunVitals: vi.fn().mockResolvedValue({
    range: "1h", bucket_ms: 120000, total: 0, error_ratio: 0, p95_ms: null,
    buckets: [], duration_bins: [], duration_matrix: [],
  }),
  getRunTimeline: vi.fn().mockResolvedValue({ range: "1h", buckets: [], spawns: [] }),
} }));
import DiagnosisView from "../components/DiagnosisView";

describe("DiagnosisView", () => {
  it("catalog → spawn detail → breadcrumb back to catalog", async () => {
    render(<DiagnosisView />);
    fireEvent.click((await screen.findByText("Bad")).closest("[data-testid='cat-row']")!);
    const bc = await screen.findByTestId("diag-breadcrumb");     // breadcrumb appears in spawn view
    expect(bc.textContent).toContain("诊断台");
    fireEvent.click(screen.getByText("诊断台"));                 // breadcrumb root → back to catalog
    await waitFor(() => expect(screen.getByText("Bad")).toBeTruthy());
  });
});
