import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";

vi.mock("../api/client", () => ({ api: {
  getRunTimeline: vi.fn(),
} }));

import { api } from "../api/client";
import AnomalyTimeline from "../components/AnomalyTimeline";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function makeCells() {
  return Array.from({ length: 24 }, (_, i) => ({
    sev: i === 3 ? "red" : i === 5 ? "amber" : i === 10 ? "green" : "none",
    count: i === 3 ? 4 : 0,
    errors: i === 3 ? 2 : 0,
  }));
}

function makeTimeline() {
  const buckets = Array.from({ length: 24 }, (_, i) => `2026-07-07T${String(i).padStart(2, "0")}:00:00Z`);
  return {
    range: "24h",
    buckets,
    spawns: [
      { spawn_id: 1, spawn_name: "Bad", cells: makeCells() },
    ],
  };
}

describe("AnomalyTimeline", () => {
  it("renders 24 cells per spawn and calls onSelectSpawn when label clicked", async () => {
    (api.getRunTimeline as any).mockResolvedValue(makeTimeline());
    const onSel = vi.fn();
    render(<AnomalyTimeline range="24h" onSelectSpawn={onSel} />);
    const cells = await screen.findAllByTestId("tl-cell");
    expect(cells.length).toBe(24);
    fireEvent.click(screen.getByText("Bad"));
    expect(onSel).toHaveBeenCalledWith(1, "Bad");
  });

  it("shows muted placeholder when there are no spawns", async () => {
    (api.getRunTimeline as any).mockResolvedValue({ range: "24h", buckets: [], spawns: [] });
    render(<AnomalyTimeline range="24h" onSelectSpawn={() => {}} />);
    expect(await screen.findByText("暂无运行数据")).toBeTruthy();
  });

  it("refetches when range changes", async () => {
    (api.getRunTimeline as any).mockResolvedValue(makeTimeline());
    const { rerender } = render(<AnomalyTimeline range="1h" onSelectSpawn={() => {}} />);
    await screen.findAllByTestId("tl-cell");
    rerender(<AnomalyTimeline range="all" onSelectSpawn={() => {}} />);
    expect(api.getRunTimeline).toHaveBeenCalledWith("all");
  });
});
