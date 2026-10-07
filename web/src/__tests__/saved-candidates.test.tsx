import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import SavedCandidates from "../components/SavedCandidates";
import * as discovery from "../api/discovery";
import i18n from "../i18n";
import { ConfirmHost } from "../components/kit";

vi.mock("../api/discovery");

describe("SavedCandidates", () => {
  beforeEach(() => { vi.resetAllMocks(); void i18n.changeLanguage("en"); });
  it("lists candidates on mount and deletes", async () => {
    (discovery.listCandidates as any).mockResolvedValue([
      { id: 1, full_name: "o/r", html_url: "u", saved_at: null,
        snapshot: { repo: { full_name: "o/r" }, trust: { tier: "high" }, suggestion: { is_mcp: true } } },
    ]);
    (discovery.deleteCandidate as any).mockResolvedValue(undefined);
    render(<SavedCandidates onPrefillMcp={vi.fn()} />);
    expect(await screen.findByText("o/r")).toBeInTheDocument();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(screen.getByRole("button", { name: /delete/i }));
    // 0.1.55: the row leaves at once; the delete is sent only when the Undo toast runs out.
    expect(screen.queryByText("o/r")).toBeNull();
    expect(discovery.deleteCandidate).not.toHaveBeenCalled();
    vi.advanceTimersByTime(6100);
    vi.useRealTimers();
    await waitFor(() => expect(discovery.deleteCandidate).toHaveBeenCalledWith(1));
  });
});
