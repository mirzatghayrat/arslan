import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RunReplay from "../components/RunReplay";
import type { RunDetailDto } from "../api/client.types";

const scored: RunDetailDto = {
  run: { id: 7, conversation_id: "c1", spawn_id: 1, spawn_name: "Mermer",
    user_message: "查天气", total_ms: 1500, task_tokens: 42,
    status: "scored", overall_score: 8, overall_badge: "good" },
  steps: [
    { seq: 0, kind: "route", ref: { spawn_name: "Mermer" }, detail: {}, duration_ms: 80 },
    { seq: 1, kind: "dispatch", ref: { spawn_name: "Mermer" }, detail: {}, duration_ms: 1200 },
  ],
  evaluations: [
    { dimension: "routing", status: "pass", score: 9, comment: "选对了人" },
    { dimension: "completion", status: "warn", score: 6, comment: "略简略" },
  ],
};

const recording: RunDetailDto = {
  ...scored,
  run: { ...scored.run, status: "recorded", overall_score: null, overall_badge: null },
  evaluations: [],
};

vi.mock("../api/client", () => ({
  api: { getRun: vi.fn() },
}));
import { api } from "../api/client";

describe("RunReplay", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders KPI cards, steps, and dimensions when scored", async () => {
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue(scored);
    render(<RunReplay runId={7} onClose={() => {}} />);

    await screen.findByText("交给 Mermer 处理");
    expect(screen.getByText("查天气")).toBeTruthy();
    expect(screen.getByText("选对了人")).toBeTruthy();
    expect(screen.getByText("42")).toBeTruthy();
  });

  it("shows 评分中 while not scored, then refreshes", async () => {
    (api.getRun as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(recording)
      .mockResolvedValue(scored);
    render(<RunReplay runId={7} onClose={() => {}} pollMs={10} />);

    await screen.findByText(/评分中/);
    await waitFor(() => expect(screen.getByText("选对了人")).toBeTruthy());
  });
});
