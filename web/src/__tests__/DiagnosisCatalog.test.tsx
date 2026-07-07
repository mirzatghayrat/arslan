import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../api/client", () => ({ api: {
  getRunCatalog: vi.fn().mockResolvedValue({ range: "1h",
    fleet: { run_count: 8, error_ratio: 0.12, p95_ms: 18600, pass_rate: 78, tokens_sum: 48000 },
    spawns: [
      { spawn_id: 1, spawn_name: "Bad", model: "qwen", run_count: 5, error_ratio: 0.2, p95_ms: 31400, pass_rate: 40, avg_score: 5.2, tokens_sum: 3100, health: "red", score_trend: [6,5,5.2] },
      { spawn_id: 2, spawn_name: "Good", model: "gpt", run_count: 3, error_ratio: 0, p95_ms: 6000, pass_rate: 100, avg_score: 8.1, tokens_sum: 2300, health: "green", score_trend: [8,8.1] },
    ] }),
  getRunAnomalies: vi.fn().mockResolvedValue([]),
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
    fireEvent.click(screen.getByText("24h"));
    await waitFor(() => expect(api.getRunCatalog).toHaveBeenCalledWith("24h"));
  });
  it("clicking a spawn row calls onSelectSpawn", async () => {
    const onSel = vi.fn();
    render(<DiagnosisCatalog onClose={() => {}} onSelectSpawn={onSel} />);
    fireEvent.click((await screen.findByText("Bad")).closest("[data-testid='cat-row']")!);
    expect(onSel).toHaveBeenCalledWith(1, "Bad");
  });
});
