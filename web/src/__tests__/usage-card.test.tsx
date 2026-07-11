import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../api/client", () => ({
  api: {
    getUsageSummary: vi.fn().mockResolvedValue({
      range: "7d",
      rows: [
        { provider: "openai", model: "gpt-4o-mini", scope: "answer", tokens_total: 15000, usd: 0.021, estimated_any: false },
        { provider: "ollama", model: "qwen3", scope: "spawn", tokens_total: 2000, usd: null, estimated_any: true },
      ],
      daily: [
        { date: "2026-07-10", tokens_total: 9000 },
        { date: "2026-07-11", tokens_total: 8000 },
      ],
      not_covered: ["optimizer", "compare_judge"],
    }),
  },
}));
import UsageCard from "../components/UsageCard";
import { api } from "../api/client";

describe("UsageCard (Diagnostics 用量卡, S3-M3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders provider×model rows: ≈ on estimated rows, no $ figure for unknown usd", async () => {
    render(<UsageCard />);
    expect(await screen.findByText("gpt-4o-mini")).toBeTruthy();
    const rows = screen.getAllByTestId("usage-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("15k");
    expect(rows[0].textContent).toContain("$0.02");
    expect(rows[0].textContent).not.toContain("≈");
    expect(rows[1].textContent).toContain("≈");
    expect(rows[1].textContent).not.toContain("$");
  });

  it("renders the daily tokens sparkline", async () => {
    render(<UsageCard />);
    await screen.findByText("gpt-4o-mini");
    expect(screen.getByTestId("usage-daily-spark")).toBeTruthy();
  });

  it("renders the not_covered footnote list", async () => {
    render(<UsageCard />);
    await screen.findByText("gpt-4o-mini");
    const fn = screen.getByTestId("usage-notcovered");
    expect(fn.textContent).toContain("optimizer");
    expect(fn.textContent).toContain("compare_judge");
  });

  it("range switch refetches with the new range", async () => {
    render(<UsageCard />);
    await screen.findByText("gpt-4o-mini");
    expect(api.getUsageSummary).toHaveBeenCalledWith("7d");
    fireEvent.click(screen.getByTestId("usage-range-30d"));
    await waitFor(() => expect(api.getUsageSummary).toHaveBeenCalledWith("30d"));
  });
});
