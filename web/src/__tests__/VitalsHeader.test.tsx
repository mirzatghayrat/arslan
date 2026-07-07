import { render, screen, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";

vi.mock("../api/client", () => ({ api: {
  getRunVitals: vi.fn(),
} }));

import { api } from "../api/client";
import VitalsHeader from "../components/VitalsHeader";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function makeVitals(overrides: Partial<Record<string, unknown>> = {}) {
  const buckets = Array.from({ length: 30 }, (_, i) => ({ t: `2026-07-07T00:${String(i).padStart(2, "0")}:00Z`, count: i % 3, errors: i % 5 === 0 ? 1 : 0 }));
  const duration_bins = ["<1s", "1-3s", "3-6s", "6-12s", "12-30s", ">30s"];
  const duration_matrix = duration_bins.map((_, bi) => Array.from({ length: 30 }, (_, ti) => (bi === 2 && ti === 5 ? 4 : 0)));
  return {
    range: "1h",
    bucket_ms: 120000,
    total: 3,
    error_ratio: 0.1,
    p95_ms: 4200,
    buckets,
    duration_bins,
    duration_matrix,
    ...overrides,
  };
}

describe("VitalsHeader", () => {
  it("renders hero total and a heatmap echart when there is data", async () => {
    (api.getRunVitals as any).mockResolvedValue(makeVitals());
    render(<VitalsHeader range="1h" />);
    expect(await screen.findByText("3")).toBeTruthy();
    expect(screen.getAllByTestId("echart").length).toBeGreaterThan(0);
    expect(api.getRunVitals).toHaveBeenCalledWith("1h");
  });

  it("shows a muted empty state when total is 0", async () => {
    (api.getRunVitals as any).mockResolvedValue(makeVitals({ total: 0, duration_matrix: [[0], [0], [0], [0], [0], [0]] }));
    render(<VitalsHeader range="24h" />);
    expect(await screen.findByText("暂无运行数据(仅分身派发时记录)")).toBeTruthy();
    expect(screen.queryByTestId("echart")).toBeNull();
  });

  it("refetches when range changes", async () => {
    (api.getRunVitals as any).mockResolvedValue(makeVitals());
    const { rerender } = render(<VitalsHeader range="1h" />);
    await screen.findByText("3");
    rerender(<VitalsHeader range="all" />);
    expect(api.getRunVitals).toHaveBeenCalledWith("all");
  });
});
