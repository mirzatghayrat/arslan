/**
 * Keyboard triage over the memory inbox (F2).
 *
 * The hazard this has to survive is stated in the component itself: three of the
 * five proposal kinds are IRREVERSIBLE — a real DELETE, or a whole-array
 * overwrite — and "it was one keystroke" is not a story anyone can act on
 * afterwards. So the interesting tests here are not that the shortcuts work,
 * they are that the fast path cannot reach the destructive kinds.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../../../api/client", () => ({
  api: {
    listMemoryProposals: vi.fn(),
    acceptMemoryProposal: vi.fn(),
    dismissMemoryProposal: vi.fn(),
  },
}));

import BrainProposalInbox from "../BrainProposalInbox";
import { api } from "../../../api/client";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const P = (over: Record<string, unknown> = {}) => ({
  id: 1, kind: "supersede_suspect", table_name: "user_facts", new_id: 2, old_id: 1,
  reason: "r", status: "pending", provenance: {}, created_at: null,
  resolved_at: null, old_excerpt: "before", new_excerpt: "after", ...over,
});

const list = () => screen.getByTestId("proposal-inbox");
const rows = () => screen.getAllByTestId("proposal-row");
const cursorAt = () => rows().findIndex((r) => r.getAttribute("data-cursor") === "1");

beforeEach(() => {
  vi.clearAllMocks();
  m.acceptMemoryProposal.mockResolvedValue(P({ status: "accepted" }));
  m.dismissMemoryProposal.mockResolvedValue(P({ status: "dismissed" }));
});

describe("moving through the list", () => {
  beforeEach(() => {
    m.listMemoryProposals.mockResolvedValue([P({ id: 1 }), P({ id: 2 }), P({ id: 3 })]);
  });

  it("starts on the first row", async () => {
    render(<BrainProposalInbox />);
    await screen.findAllByTestId("proposal-row");
    expect(cursorAt()).toBe(0);
  });

  it("J goes down and K comes back", async () => {
    render(<BrainProposalInbox />);
    await screen.findAllByTestId("proposal-row");
    fireEvent.keyDown(list(), { key: "j" });
    expect(cursorAt()).toBe(1);
    fireEvent.keyDown(list(), { key: "k" });
    expect(cursorAt()).toBe(0);
  });

  it("the arrows do the same, for people who do not use vim", async () => {
    render(<BrainProposalInbox />);
    await screen.findAllByTestId("proposal-row");
    fireEvent.keyDown(list(), { key: "ArrowDown" });
    expect(cursorAt()).toBe(1);
    fireEvent.keyDown(list(), { key: "ArrowUp" });
    expect(cursorAt()).toBe(0);
  });

  it("does not run off either end", async () => {
    render(<BrainProposalInbox />);
    await screen.findAllByTestId("proposal-row");
    fireEvent.keyDown(list(), { key: "k" });
    expect(cursorAt()).toBe(0);
    for (let i = 0; i < 8; i++) fireEvent.keyDown(list(), { key: "j" });
    expect(cursorAt()).toBe(2);
  });
});

describe("acting on the reversible kinds", () => {
  beforeEach(() => {
    m.listMemoryProposals.mockResolvedValue([P({ id: 1 }), P({ id: 2 })]);
  });

  it("1 accepts the row under the cursor — not the first one", async () => {
    render(<BrainProposalInbox />);
    await screen.findAllByTestId("proposal-row");
    fireEvent.keyDown(list(), { key: "j" });
    fireEvent.keyDown(list(), { key: "1" });
    await waitFor(() => expect(m.acceptMemoryProposal).toHaveBeenCalledWith(2));
  });

  it("3 dismisses the row under the cursor", async () => {
    render(<BrainProposalInbox />);
    await screen.findAllByTestId("proposal-row");
    fireEvent.keyDown(list(), { key: "3" });
    await waitFor(() => expect(m.dismissMemoryProposal).toHaveBeenCalledWith(1));
  });
});

describe("the destructive kinds are not reachable by one keystroke", () => {
  // delete_suspect is a real DELETE; preference_overwrite_suspect replaces a
  // whole array. Neither can be undone, which is why the mouse path makes them
  // confirm — and why the keyboard must not be a way around that.
  const DESTRUCTIVE = ["delete_suspect", "preference_overwrite_suspect"];

  it.each(DESTRUCTIVE)("1 on a %s opens the confirm instead of accepting", async (kind) => {
    m.listMemoryProposals.mockResolvedValue([P({ id: 9, kind })]);
    render(<BrainProposalInbox />);
    await screen.findAllByTestId("proposal-row");
    fireEvent.keyDown(list(), { key: "1" });
    await waitFor(() => expect(screen.getByTestId("confirm-prompt")).toBeInTheDocument());
    expect(m.acceptMemoryProposal).not.toHaveBeenCalled();
  });

  it("holding 1 down never gets through — repeats only re-open the confirm", async () => {
    // The realistic accident: a key held or hammered during fast triage.
    m.listMemoryProposals.mockResolvedValue([P({ id: 9, kind: "delete_suspect" })]);
    render(<BrainProposalInbox />);
    await screen.findAllByTestId("proposal-row");
    for (let i = 0; i < 5; i++) fireEvent.keyDown(list(), { key: "1" });
    await waitFor(() => expect(screen.getByTestId("confirm-prompt")).toBeInTheDocument());
    expect(m.acceptMemoryProposal).not.toHaveBeenCalled();
  });

  it("Escape backs out of the confirm", async () => {
    m.listMemoryProposals.mockResolvedValue([P({ id: 9, kind: "delete_suspect" })]);
    render(<BrainProposalInbox />);
    await screen.findAllByTestId("proposal-row");
    fireEvent.keyDown(list(), { key: "1" });
    await screen.findByTestId("confirm-prompt");
    fireEvent.keyDown(list(), { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("confirm-prompt")).toBeNull());
    expect(m.acceptMemoryProposal).not.toHaveBeenCalled();
  });

  it("3 still dismisses a destructive proposal — declining is always safe", async () => {
    m.listMemoryProposals.mockResolvedValue([P({ id: 9, kind: "delete_suspect" })]);
    render(<BrainProposalInbox />);
    await screen.findAllByTestId("proposal-row");
    fireEvent.keyDown(list(), { key: "3" });
    await waitFor(() => expect(m.dismissMemoryProposal).toHaveBeenCalledWith(9));
  });
});

describe("the list shrinking underneath you", () => {
  it("the cursor stays in range after the last row is actioned", async () => {
    m.listMemoryProposals
      .mockResolvedValueOnce([P({ id: 1 }), P({ id: 2 })])
      .mockResolvedValue([P({ id: 1 })]);
    render(<BrainProposalInbox />);
    await screen.findAllByTestId("proposal-row");
    fireEvent.keyDown(list(), { key: "j" });          // cursor on the last row
    fireEvent.keyDown(list(), { key: "3" });          // which then disappears
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(cursorAt()).toBe(0);
  });

  it("an empty inbox swallows the keys rather than throwing", async () => {
    // Asserted through a console.error spy as well as the surviving DOM: without
    // it, a crash here shows up as an unhandled rejection that fails the RUN
    // without failing this TEST, which is a red build nobody can attribute.
    // A throw inside a React event handler surfaces as an `error` event on
    // window, NOT as console.error and NOT as a failed assertion — so without
    // this listener a crash here fails the RUN without failing this TEST, which
    // is a red build nobody can attribute. (Learned by mutating the guard away
    // and watching exactly that happen.)
    const errors: unknown[] = [];
    const onError = (e: Event) => { errors.push((e as ErrorEvent).message ?? e); };
    window.addEventListener("error", onError);
    const spy = vi.spyOn(console, "error").mockImplementation((...a) => { errors.push(a); });
    try {
      m.listMemoryProposals.mockResolvedValue([]);
      render(<BrainProposalInbox />);
      await screen.findByTestId("inbox-empty");
      fireEvent.keyDown(list(), { key: "1" });
      fireEvent.keyDown(list(), { key: "3" });
      fireEvent.keyDown(list(), { key: "j" });
      expect(m.acceptMemoryProposal).not.toHaveBeenCalled();
      expect(m.dismissMemoryProposal).not.toHaveBeenCalled();
      expect(screen.getByTestId("inbox-empty")).toBeInTheDocument();
      expect(errors).toEqual([]);
    } finally {
      spy.mockRestore();
      window.removeEventListener("error", onError);
    }
  });
});
