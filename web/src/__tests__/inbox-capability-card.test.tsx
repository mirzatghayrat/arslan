/** 0.1.61 §A4 (PR 2b final review, M6): a new capability is allowed only where its whole card is shown (installing code wants the whole card,
 *  0.1.57). The server now refuses the Inbox's yes to such a card (`open_in_arslan`), so the Inbox must not offer it: "Open in Arslan" stands
 *  where Allow would, with the island's words and a line that says why, and no choice of how long (nothing is allowed from here). Saying no
 *  stays. Every other kind of card is unchanged. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import * as client from "../api/client";
import InboxApprovals from "../components/proactive/InboxApprovals";
import { ANSWER_GUARD_MS } from "../components/kit";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
/** A card that has just appeared in the Inbox answers 500 ms later (kit/guard.ts). */
const pastGuard = () => act(async () => { await new Promise((r) => setTimeout(r, ANSWER_GUARD_MS + 30)); });

const row = (frame: Record<string, unknown>) => ({ call_id: String(frame.call_id), conversation_id: "conv-7", opened_at: 1000, expires_at: 1300, frame });
function serve(rows: unknown[]) {
  return vi.spyOn(client, "request").mockImplementation(async (path: string) => (path === "/approvals/pending" ? rows : { ok: true }) as never);
}
const CAP = { type: "propose_action", call_id: "cap1", kind: "capability", target: "srv", detail: "Reads .xlsx", title: "Add the srv tool?",
  perm_kind: "capability", options: ["once"] };
const APP = { type: "propose_action", call_id: "app1", kind: "desktop_app", target: "Notes", detail: "", title: "Use Notes?", perm_kind: "app",
  options: ["task", "conversation"] };
const answers = (req: ReturnType<typeof serve>) => req.mock.calls.filter(([p, init]) => String(p).includes("/answer") && (init as RequestInit | undefined)?.method === "POST");

describe("a capability card in the Inbox", () => {
  it("shows Open in Arslan where Allow would be, with the reason, and no choice of how long", async () => {
    serve([row(CAP)]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    const card = await screen.findByTestId("held-card");
    expect(screen.queryByTestId("action-allow")).toBeNull();
    expect(screen.queryByTestId("action-card")).toBeNull();
    expect(screen.getByTestId("held-open")).toHaveTextContent("inbox.openInArslan");
    expect(screen.getByTestId("held-reason")).toHaveTextContent("inbox.heldCapability");
    expect(screen.getByTestId("held-title")).toHaveTextContent("Add the srv tool?");
    expect(screen.getByTestId("held-subject")).toHaveTextContent("srv");
    expect(card.querySelector("input[type=radio]")).toBeNull();                 // nothing is allowed from here: no choice of how long
    expect(screen.getByTestId("held-deny")).toBeInTheDocument();
  });

  it("opens the conversation it was asked in, and answers nothing", async () => {
    const req = serve([row(CAP)]);
    const opened = vi.fn();
    render(<InboxApprovals onOpenConversation={opened} />);
    await screen.findByTestId("held-card");
    await pastGuard();
    fireEvent.click(screen.getByTestId("held-open"));
    expect(opened).toHaveBeenCalledWith("conv-7");
    opened.mockClear();
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });                 // ⌘⏎ is the same button
    expect(opened).toHaveBeenCalledWith("conv-7");
    expect(answers(req)).toEqual([]);
  });

  it("can still be declined, with the user's note", async () => {
    const req = serve([row(CAP)]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    await screen.findByTestId("held-card");
    await pastGuard();
    fireEvent.click(screen.getByTestId("held-deny"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/cap1/answer",
      { method: "POST", body: JSON.stringify({ approve: false, source: "inbox" }) }));
  });

  it("a No with a note carries the note", async () => {
    const req = serve([row(CAP)]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    await screen.findByTestId("held-card");
    await pastGuard();
    fireEvent.click(screen.getByTestId("held-note-open"));
    fireEvent.change(screen.getByTestId("held-note-input"), { target: { value: "use the one I have" } });
    fireEvent.click(screen.getByTestId("held-note-send"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/cap1/answer",
      { method: "POST", body: JSON.stringify({ approve: false, source: "inbox", note: "use the one I have" }) }));
  });

  it("says who is asking: a job when the frame says background", async () => {
    serve([row({ ...CAP, background: true })]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    expect(await screen.findByRole("alertdialog")).toHaveAccessibleName("jobs.askingBadge");
    cleanup();
    serve([row(CAP)]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    expect(await screen.findByRole("alertdialog")).toHaveAccessibleName("kit.whoArslan");
  });

  it("is the only kind that is held: an app card keeps its Allow and its choices", async () => {
    serve([row(APP)]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    await screen.findByTestId("action-card");
    expect(screen.getByTestId("action-allow")).toHaveTextContent("hands.allow");
    expect(screen.queryByTestId("held-card")).toBeNull();
    expect(screen.getByTestId("action-scope")).toBeInTheDocument();
    expect(screen.getByTestId("action-card")).not.toHaveTextContent("inbox.heldCapability");
  });

  it.each([
    ["an action card", CAP, "action-allow"],
    ["a run-command card", { type: "propose_run_command", call_id: "r1", pretty: "npx srv", reason: "", options: ["once"], perm_kind: "capability" }, "runcmd-run"],
    ["a write card", { type: "propose_workspace_write", call_id: "w1", workspace: "/w", action: "write_file", path: "a.md", options: ["once"], perm_kind: "capability" }, "wswrite-allow"],
    ["a schedule card", { type: "propose_schedule", call_id: "s1", name: "Brief", when: "every: 60", options: ["once"], perm_kind: "capability" }, "schedule-allow"],
  ])("%s that carries the kind is held too: the server refuses its yes whatever the card type", async (_what, frame, allow) => {
    serve([row(frame)]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    await screen.findByTestId("held-card");
    expect(screen.queryByTestId(allow)).toBeNull();
    expect(screen.getByTestId("held-open")).toHaveTextContent("inbox.openInArslan");
    expect(screen.getByTestId("held-title").textContent?.trim()).not.toBe("");
  });

  it.each(["Capability", " capability", ["capability"], null, ""])("a permission kind of %j is not the capability kind: the card is the usual one", async (permKind) => {
    serve([row({ ...APP, perm_kind: permKind })]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    await screen.findByTestId("action-card");
    expect(screen.queryByTestId("held-card")).toBeNull();
  });
});
