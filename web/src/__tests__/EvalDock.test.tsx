import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("../api/client", () => ({ api: {
  getConversationRecap: vi.fn().mockResolvedValue({
    summary: { run_count: 2, avg_score: 7.8, growth_count: 1 },
    items: [
      { kind: "run", created_at: "2026-07-08T10:02:00", run_id: 9, spawn_name: "Deck Master",
        user_message: "出 deck", overall_score: 9.0, total_ms: 6500 },
      { kind: "distill", created_at: "2026-07-08T10:00:00", ref: { spawn_name: "Data Analyst" },
        summary: "Arslan 亲自做 → 喂给 Data Analyst 学习" },
    ],
  }),
} }));
import EvalDock from "../components/EvalDock";

describe("EvalDock recap timeline", () => {
  it("renders a scoped recap timeline (runs + growth) with summary", async () => {
    const onOpen = vi.fn();
    render(<EvalDock conversationId="c" onOpenDiagnosis={onOpen} />);
    expect(await screen.findByText(/Deck Master/)).toBeTruthy();          // run item
    expect(screen.getByText(/Data Analyst/)).toBeTruthy();               // distill item
    expect(screen.getByText(/7.8/)).toBeTruthy();                        // avg in summary
    fireEvent.click(screen.getByText(/诊断台/));                          // link → standalone view
    expect(onOpen).toHaveBeenCalled();
  });

  it("empty conversation shows an empty state", async () => {
    const { api } = await import("../api/client");
    (api.getConversationRecap as any).mockResolvedValueOnce(
      { summary: { run_count: 0, avg_score: null, growth_count: 0 }, items: [] });
    render(<EvalDock conversationId="c2" onOpenDiagnosis={() => {}} />);
    expect(await screen.findByText(/还没有运行|还没有.*记录/)).toBeTruthy();
  });

  it("renders nothing without a conversation id", () => {
    const { container } = render(<EvalDock onOpenDiagnosis={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
});
