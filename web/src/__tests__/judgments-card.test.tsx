/** 0.1.52 S2: Activity › Judgments — hidden when empty; verdict, shadow tag, your answer. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) =>
  o ? `${k}:${JSON.stringify(o)}` : k, i18n: { language: "en" } }) }));
const request = vi.fn();
vi.mock("../api/client", () => ({ request: (...a: unknown[]) => request(...a) }));

import JudgmentsCard from "../components/JudgmentsCard";

afterEach(() => { cleanup(); request.mockReset(); });

describe("JudgmentsCard", () => {
  it("shows nothing until there is a judgment", async () => {
    request.mockResolvedValue({ items: [] });
    const { container } = render(<JudgmentsCard />);
    await waitFor(() => expect(request).toHaveBeenCalledWith("/judgments?limit=20"));
    expect(container.innerHTML).toBe("");
  });

  it("lists the question, the judge's view and what you chose", async () => {
    request.mockResolvedValue({ items: [
      { id: 1, point: "tool.approval", mode: "shadow", verdict: false, probability: 0.2, latency_ms: 400,
        outcome: "declined", created_at: "2026-10-03T08:00:00Z" },
      { id: 2, point: "memory.worth", mode: "active", verdict: null, probability: null, latency_ms: 2000,
        outcome: null, created_at: "2026-10-03T08:01:00Z" },
    ] });
    render(<JudgmentsCard />);
    const row = await screen.findByTestId("judgment-1");
    expect(row).toHaveTextContent("activityPage.pointApproval");
    expect(row).toHaveTextContent("activityPage.judgeShadow");
    expect(row).toHaveTextContent('activityPage.judgeNo:{"p":80}');
    expect(row).toHaveTextContent("activityPage.youDeclined");
    expect(screen.getByTestId("judgment-2")).toHaveTextContent("activityPage.judgeNoAnswer");
    expect(screen.getByTestId("judgment-2")).not.toHaveTextContent("activityPage.judgeShadow");
  });
});
