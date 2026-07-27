import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("../api/client", () => ({ api: {
  // S3-M3: the dock also fetches the conversation cumulative usage (own test file).
  getConversationUsage: vi.fn().mockResolvedValue({
    tokens_total: 0, usd_total: null, usd_partial: false, estimated_any: false, by_scope: [],
  }),
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
  it("collapsed by default; summary inline; expands to the timeline", async () => {
    const onOpen = vi.fn();
    render(<EvalDock conversationId="c" onOpenDiagnosis={onOpen} />);
    // summary shows collapsed (inline in the header); timeline is hidden until expand
    expect(await screen.findByText("eval.dock_summary")).toBeTruthy();
    expect(screen.queryByText(/Deck Master/)).toBeNull();
    fireEvent.click(screen.getByText("eval.dock_title"));                    // expand
    expect(await screen.findByText(/Deck Master/)).toBeTruthy();          // run item now visible
    expect(screen.getByText(/Data Analyst/)).toBeTruthy();               // distill item
    fireEvent.click(screen.getByText(/Diagnostics/));                    // link → standalone view
    expect(onOpen).toHaveBeenCalled();
  });

  it("empty conversation shows an empty state when expanded", async () => {
    const { api } = await import("../api/client");
    (api.getConversationRecap as any).mockResolvedValueOnce(
      { summary: { run_count: 0, avg_score: null, growth_count: 0 }, items: [] });
    render(<EvalDock conversationId="c2" onOpenDiagnosis={() => {}} />);
    fireEvent.click(await screen.findByText("eval.dock_title"));            // expand
    expect(await screen.findByText("eval.dock_empty")).toBeTruthy();
  });

  it("renders nothing without a conversation id", () => {
    const { container } = render(<EvalDock onOpenDiagnosis={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
});
