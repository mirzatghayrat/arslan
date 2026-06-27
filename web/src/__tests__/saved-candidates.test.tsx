import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import SavedCandidates from "../components/SavedCandidates";
import * as discovery from "../api/discovery";

vi.mock("../api/discovery");

describe("SavedCandidates", () => {
  beforeEach(() => vi.resetAllMocks());
  it("lists candidates on mount and deletes", async () => {
    (discovery.listCandidates as any).mockResolvedValue([
      { id: 1, full_name: "o/r", html_url: "u", saved_at: null,
        snapshot: { repo: { full_name: "o/r" }, trust: { tier: "high" }, suggestion: { is_mcp: true } } },
    ]);
    (discovery.deleteCandidate as any).mockResolvedValue(undefined);
    render(<SavedCandidates onPrefillMcp={vi.fn()} />);
    expect(await screen.findByText("o/r")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /delete/i }));
    await waitFor(() => expect(discovery.deleteCandidate).toHaveBeenCalledWith(1));
  });
});
