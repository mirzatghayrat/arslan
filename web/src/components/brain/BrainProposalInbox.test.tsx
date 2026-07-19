import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../../api/client", () => ({
  api: {
    listMemoryProposals: vi.fn(),
    acceptMemoryProposal: vi.fn(),
    dismissMemoryProposal: vi.fn(),
  },
}));

import BrainProposalInbox from "./BrainProposalInbox";
import { api } from "../../api/client";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const P = (over: Record<string, unknown> = {}) => ({
  id: 1, kind: "supersede_suspect", table_name: "user_facts", new_id: 2, old_id: 1,
  reason: "fuzzy near-dup", status: "pending", provenance: {}, created_at: null,
  resolved_at: null, old_excerpt: "住在北京", new_excerpt: "住在上海", ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  m.listMemoryProposals.mockResolvedValue([P()]);
  m.acceptMemoryProposal.mockResolvedValue(P({ status: "accepted" }));
  m.dismissMemoryProposal.mockResolvedValue(P({ status: "dismissed" }));
});

describe("BrainProposalInbox", () => {
  it("renders a pending proposal with a before/after diff", async () => {
    render(<BrainProposalInbox />);
    const row = await screen.findByTestId("proposal-row");
    expect(row.textContent).toContain("住在北京");
    expect(row.textContent).toContain("住在上海");
  });

  it("a REVERSIBLE proposal accepts in one click", async () => {
    render(<BrainProposalInbox />);
    fireEvent.click(await screen.findByTestId("accept-btn"));
    await waitFor(() => expect(m.acceptMemoryProposal).toHaveBeenCalledWith(1));
  });

  it.each([
    ["delete_suspect"],
    ["preference_overwrite_suspect"],
  ])("🔴 %s CANNOT be accepted in one click — it is unrecoverable", async (kind) => {
    // delete_suspect really DELETEs the row (or wipes a spawn's whole memory_facts
    // array); preference_overwrite replaces the array outright. undo-supersede cannot
    // reach either — it only clears a pointer on a row that still exists. A blanket
    // triage flow over a mixed inbox would destroy data on one mis-keystroke.
    m.listMemoryProposals.mockResolvedValue([P({ kind })]);
    render(<BrainProposalInbox />);

    expect(await screen.findByTestId("destructive-badge")).toBeTruthy();
    expect(screen.queryByTestId("accept-btn")).toBeNull();

    fireEvent.click(screen.getByTestId("accept-destructive-btn"));
    expect(await screen.findByTestId("confirm-prompt")).toBeTruthy();
    expect(m.acceptMemoryProposal).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("confirm-accept-btn"));
    await waitFor(() => expect(m.acceptMemoryProposal).toHaveBeenCalledWith(1));
  });

  it("cancelling the confirmation does not accept", async () => {
    m.listMemoryProposals.mockResolvedValue([P({ kind: "delete_suspect" })]);
    render(<BrainProposalInbox />);
    fireEvent.click(await screen.findByTestId("accept-destructive-btn"));
    fireEvent.click(screen.getByTestId("confirm-cancel-btn"));
    await waitFor(() => expect(screen.queryByTestId("confirm-prompt")).toBeNull());
    expect(m.acceptMemoryProposal).not.toHaveBeenCalled();
  });

  it("🔴 refetches after accepting — siblings are auto-dismissed server-side", async () => {
    // The server dismisses sibling proposals for the same (kind, table, old_id,
    // conversation) with nothing in the response to say so, and the accept response
    // omits the excerpt fields the list carries. Patching the one row would leave the
    // inbox showing proposals that no longer exist.
    render(<BrainProposalInbox />);
    await screen.findByTestId("proposal-row");
    expect(m.listMemoryProposals).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("accept-btn"));
    await waitFor(() => expect(m.listMemoryProposals).toHaveBeenCalledTimes(2));
  });

  it("dismiss is always one click — it writes nothing", async () => {
    m.listMemoryProposals.mockResolvedValue([P({ kind: "delete_suspect" })]);
    render(<BrainProposalInbox />);
    fireEvent.click(await screen.findByTestId("dismiss-btn"));
    await waitFor(() => expect(m.dismissMemoryProposal).toHaveBeenCalledWith(1));
  });

  it("surfaces a rejected accept instead of silently doing nothing", async () => {
    m.acceptMemoryProposal.mockRejectedValue(new Error("409 spawn memory changed"));
    render(<BrainProposalInbox />);
    fireEvent.click(await screen.findByTestId("accept-btn"));
    expect((await screen.findByRole("alert")).textContent).toContain("409");
  });

  it("uses based_on as the BEFORE for a preference overwrite, not the live value", async () => {
    // They differ exactly when someone changed the spawn since the proposal was filed —
    // which is the case the server answers 409 for. Showing the live value would hide
    // the very drift the user needs to see.
    m.listMemoryProposals.mockResolvedValue([P({
      kind: "preference_overwrite_suspect", table_name: "spawns",
      old_excerpt: "喜欢简短; 用中文",
      provenance: { based_on: ["喜欢简短"], new_array: ["喜欢简短", "先给结论"] },
    })]);
    render(<BrainProposalInbox />);
    const row = await screen.findByTestId("proposal-row");
    expect(row.textContent).toContain("先给结论");
    expect(row.textContent).not.toContain("用中文");
  });
});
