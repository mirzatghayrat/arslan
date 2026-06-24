import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EvalSummary from "../components/EvalSummary";

vi.mock("../api/client", () => ({ api: { getRuns: vi.fn(), getRun: vi.fn() } }));
import { api } from "../api/client";
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  m.getRuns.mockResolvedValue([
    { id: 2, spawn_name: "小美", status: "scored", overall_score: 9, overall_badge: "good", total_ms: 1500, user_message: "写文案" },
    { id: 1, spawn_name: "Mermer", status: "recorded", overall_score: null, overall_badge: null, total_ms: 800, user_message: "查天气" },
  ]);
  m.getRun.mockResolvedValue({
    run: { id: 2, conversation_id: "c", spawn_id: 1, spawn_name: "小美", user_message: "写文案",
           total_ms: 1500, task_tokens: 10, status: "scored", overall_score: 9, overall_badge: "good" },
    steps: [], evaluations: [],
  });
});

describe("EvalSummary", () => {
  it("renders summary + rows", async () => {
    render(<EvalSummary onClose={() => {}} />);
    await screen.findByText("小美");
    expect(screen.getByText("Mermer")).toBeTruthy();
    expect(screen.getByText(/评分中/)).toBeTruthy();
  });

  it("drills into RunReplay on row click", async () => {
    render(<EvalSummary onClose={() => {}} />);
    const row = await screen.findByText("小美");
    fireEvent.click(row);
    await screen.findByText("编排回放");
  });

  it("shows empty state", async () => {
    m.getRuns.mockResolvedValue([]);
    render(<EvalSummary onClose={() => {}} />);
    await screen.findByText(/还没有运行记录/);
  });
});
