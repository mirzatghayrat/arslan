import { render, screen, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../api/client", () => ({
  api: {
    getConversationRecap: vi.fn().mockResolvedValue({
      summary: { run_count: 0, avg_score: null, growth_count: 0 },
      items: [],
    }),
    getConversationUsage: vi.fn().mockResolvedValue({
      tokens_total: 12500,
      usd_total: 0.021,
      usd_partial: true,
      estimated_any: true,
      by_scope: [{ scope: "answer", tokens_total: 12500, usd: 0.021 }],
    }),
  },
}));
import EvalDock from "../components/EvalDock";
import { api } from "../api/client";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

describe("EvalDock conversation cumulative usage (S3-M3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useArslanStore.setState(initialArslanState(), true);
  });

  it("renders Σ tok · $usd with ≈ (estimated_any) and + (usd_partial)", async () => {
    render(<EvalDock conversationId="c1" onOpenDiagnosis={() => {}} />);
    const line = await screen.findByTestId("conv-usage");
    expect(line.textContent).toContain("Σ");
    expect(line.textContent).toContain("≈");
    expect(line.textContent).toContain("12.5k tok");
    expect(line.textContent).toContain("$0.02");
    expect(line.textContent).toContain("+");
  });

  it("usd_total null → tokens only, no $ figure (unknown ≠ free)", async () => {
    (api.getConversationUsage as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      tokens_total: 900,
      usd_total: null,
      usd_partial: true,
      estimated_any: false,
      by_scope: [],
    });
    render(<EvalDock conversationId="c1" onOpenDiagnosis={() => {}} />);
    const line = await screen.findByTestId("conv-usage");
    expect(line.textContent).toContain("900 tok");
    expect(line.textContent).not.toContain("$");
  });

  it("refetches after a turn ends (store lastMessageId bump = stream_end landed)", async () => {
    render(<EvalDock conversationId="c1" onOpenDiagnosis={() => {}} />);
    await screen.findByTestId("conv-usage");
    expect(api.getConversationUsage).toHaveBeenCalledTimes(1);
    act(() => {
      useArslanStore.setState({ lastMessageId: 42 });
    });
    await waitFor(() =>
      expect(api.getConversationUsage).toHaveBeenCalledTimes(2),
    );
  });

  it("fetch failure hides the line silently", async () => {
    (api.getConversationUsage as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("boom"));
    render(<EvalDock conversationId="c1" onOpenDiagnosis={() => {}} />);
    await screen.findByText("eval.dock_title");
    await waitFor(() => expect(api.getConversationUsage).toHaveBeenCalled());
    expect(screen.queryByTestId("conv-usage")).toBeNull();
  });
});
