/** 0.1.61 §A4 (PR 2b Task 4): the Inbox shows a card from the permission layer as the chat does. What Task 3 settled for the chat
 *  holds here too: the command card knows its permission kind (a red step is red), a card of a kind without words of its own is asked in
 *  the model's why with the server's literal subject line under it, a kind with words keeps them and shows the why as "Arslan says",
 *  a title of spaces is no title, one long unbroken line wraps; and a call id is one entry in the queue. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import * as client from "../api/client";
import InboxApprovals from "../components/proactive/InboxApprovals";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const row = (frame: Record<string, unknown>) => ({ call_id: String(frame.call_id), conversation_id: "conv-1", opened_at: 1000, expires_at: 1300, frame });
function serve(rows: unknown[]) {
  return vi.spyOn(client, "request").mockImplementation(async (path: string) => (path === "/approvals/pending" ? rows : { ok: true }) as never);
}
const show = (rows: unknown[], onCount?: (n: number) => void) => { serve(rows); render(<InboxApprovals onOpenConversation={() => {}} onCount={onCount} />); };

const CMD = { type: "propose_run_command", call_id: "r1", pretty: "pay.sh --now", reason: "", options: ["once", "conversation"], always_label: "that command" };
const ACT = { type: "propose_action", call_id: "a1", kind: "mcp_tool", target: "rea/search", detail: "", title: "Use rea’s search?",
  options: ["task", "conversation"], perm_kind: "mcp_tool" };

describe("the command card in the Inbox knows its permission kind", () => {
  it.each([["money", true], ["app_risky", true], ["destructive", true], ["command", false]])(
    "a command card of kind %s draws Run red: %s, as in the chat", async (permKind, red) => {
    show([row({ ...CMD, perm_kind: permKind })]);
    const run = await screen.findByTestId("runcmd-run");
    expect(run.className.includes("danger")).toBe(red);
  });

  it("a once-only kind offers only the first choice, and the Inbox answers it", async () => {
    const req = serve([row({ ...CMD, perm_kind: "money", options: ["once", "conversation", "always"] })]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    await screen.findByTestId("runcmd-run");
    expect(screen.queryByTestId("runcmd-scope-conversation")).toBeNull();
    expect(screen.queryByTestId("runcmd-scope-always")).toBeNull();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/r1/answer",
      { method: "POST", body: JSON.stringify({ approve: true, source: "inbox", scope: "once" }) }));
  });
});

describe("the action card in the Inbox knows its permission kind", () => {
  it.each([["money", true], ["app_risky", true], ["destructive", true], ["mcp_tool", false]])(
    "an action card of kind %s draws Allow red: %s, as in the chat", async (permKind, red) => {
    show([row({ ...ACT, perm_kind: permKind })]);
    const card = await screen.findByTestId("action-card");
    expect(card).toHaveAttribute("data-risky", String(red));
    expect(screen.getByTestId("action-allow").className.includes("danger")).toBe(red);
  });

  it("a once-only kind offers only the first choice there too", async () => {
    show([row({ ...ACT, perm_kind: "money", options: ["once", "conversation", "always"], always_label: "pay" })]);
    await screen.findByTestId("action-card");
    expect(screen.queryByTestId("action-scope-conversation")).toBeNull();
    expect(screen.queryByTestId("action-scope-always")).toBeNull();
  });
});

describe("the write and schedule cards in the Inbox offer their choices and send the one chosen", () => {
  it("a workspace write: In this conversation is a choice, and the yes carries it", async () => {
    const req = serve([row({ type: "propose_workspace_write", call_id: "w1", workspace: "/w", action: "write_file", path: "a.md",
      options: ["once", "conversation"], perm_kind: "workspace_write" })]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    fireEvent.click(await screen.findByTestId("wswrite-scope-conversation"));
    fireEvent.click(screen.getByTestId("wswrite-allow"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/w1/answer",
      { method: "POST", body: JSON.stringify({ approve: true, source: "inbox", scope: "conversation" }) }));
  });

  it("a schedule: the same, and a No may carry a note", async () => {
    const req = serve([row({ type: "propose_schedule", call_id: "s1", name: "Brief", when: "every: 3600", options: ["once", "conversation"], perm_kind: "schedule" })]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    fireEvent.click(await screen.findByText("kit.noteLink"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "not on weekends" } });
    fireEvent.click(screen.getByText("kit.noteSend"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/s1/answer",
      { method: "POST", body: JSON.stringify({ approve: false, source: "inbox", note: "not on weekends" }) }));
  });

  it("an old write card (no options) still answers with just approve", async () => {
    const req = serve([row({ type: "propose_workspace_write", call_id: "w2", workspace: "/w", action: "edit_file", path: "a.md" })]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    expect(screen.queryByTestId("wswrite-scope-conversation")).toBeNull();
    fireEvent.click(await screen.findByTestId("wswrite-allow"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/w2/answer",
      { method: "POST", body: JSON.stringify({ approve: true, source: "inbox" }) }));
  });
});

describe("a card of a kind the card has no words for is asked in the model's why, with the server's own words under it", () => {
  it("the heading is the why; under it the frame's literal title, in the primary style, not marked as the model's", async () => {
    show([row({ ...ACT, why: "Look up the opening hours" })]);
    expect(await screen.findByTestId("action-title")).toHaveTextContent("Look up the opening hours");
    const subject = screen.getByTestId("action-subject");
    expect(subject.textContent).toBe("Use rea’s search?");
    expect(subject).toHaveAttribute("lang", "en");
    expect(subject.className).toContain("text-foreground");
    expect(subject.className).toContain("font-semibold");
    expect(subject.className).not.toContain("text-muted-foreground");
    expect(screen.queryByTestId("action-said")).toBeNull();
  });

  it("with no title it is the bare target, which is not words and so is not tagged", async () => {
    show([row({ ...ACT, title: undefined, why: "Look up the opening hours" })]);
    await screen.findByTestId("action-title");
    expect(screen.getByTestId("action-subject").textContent).toBe("rea/search");
    expect(screen.getByTestId("action-subject")).not.toHaveAttribute("lang");
  });

  it("with no why the title is the question, said once", async () => {
    show([row(ACT)]);
    expect(await screen.findByTestId("action-title")).toHaveTextContent("Use rea’s search?");
    expect(screen.queryByTestId("action-subject")).toBeNull();
    expect(screen.getAllByText("Use rea’s search?")).toHaveLength(1);
  });

  it("a title of spaces is no title: the target is the question, and the line under the why", async () => {
    show([row({ ...ACT, title: "   " })]);
    expect((await screen.findByTestId("action-title")).textContent).toBe("rea/search");
    cleanup();
    show([row({ ...ACT, title: " \n ", why: "Look up the opening hours" })]);
    expect(await screen.findByTestId("action-title")).toHaveTextContent("Look up the opening hours");
    expect(screen.getByTestId("action-subject").textContent).toBe("rea/search");
  });

  it("one long unbroken line breaks anywhere instead of spilling out of the card", async () => {
    show([row({ ...ACT, why: "https://example.com/" + "a".repeat(200) })]);
    expect((await screen.findByTestId("action-title")).className).toContain("overflow-wrap:anywhere");
    expect(screen.getByTestId("action-subject").className).toContain("break-words");
  });
});

describe("a kind with words of its own keeps them and shows the model's why as \"Arslan says\"", () => {
  const KNOWN = { ...ACT, kind: "desktop_app", target: "Notes", title: "Use Notes?", perm_kind: "app" };

  it("the heading is the card's own words; the why sits in the said slot; the frame's title is not repeated", async () => {
    show([row({ ...KNOWN, why: "Tidy the notes" })]);
    expect(await screen.findByTestId("action-title")).toHaveTextContent('hands.title.desktop_app:{"target":"Notes"}');
    expect(screen.getByTestId("action-said")).toHaveTextContent("Tidy the notes");
    expect(screen.getByTestId("action-said")).toHaveTextContent("kit.arslanSays");
    expect(screen.queryByTestId("action-subject")).toBeNull();
  });

  it("a why of spaces shows nothing; a long unbroken why breaks anywhere", async () => {
    show([row({ ...KNOWN, why: "   " })]);
    await screen.findByTestId("action-title");
    expect(screen.queryByTestId("action-said")).toBeNull();
    cleanup();
    show([row({ ...KNOWN, why: "https://example.com/" + "a".repeat(200) })]);
    expect((await screen.findByTestId("action-said")).className).toContain("overflow-wrap:anywhere");
  });
});

describe("a call id is one entry in the queue", () => {
  it("the same card listed twice is one card, counted once, with no 1 / 2 and no second page", async () => {
    const count = vi.fn();
    const same = row(CMD);
    show([same, { ...same }], count);
    await screen.findByTestId("runcmd-card");
    expect(screen.queryByTestId("ask-queue")).toBeNull();
    await waitFor(() => expect(count).toHaveBeenCalledWith(1));
    expect(count).not.toHaveBeenCalledWith(2);
    expect(screen.getByTestId("inbox-approvals").querySelector("h2")).toHaveTextContent(/^inbox\.approveNow1$/);
  });

  it("a row without a call id is no card: it could not be answered", async () => {
    const count = vi.fn();
    const { call_id: _gone, ...noId } = row(CMD);
    void _gone;
    show([row({ ...CMD, call_id: "r2", pretty: "ls" }), noId], count);
    await screen.findByTestId("runcmd-card");
    expect(screen.queryByTestId("ask-queue")).toBeNull();
    await waitFor(() => expect(count).toHaveBeenCalledWith(1));
  });

  it("two different cards are two, and the first page is the first card", async () => {
    const count = vi.fn();
    show([row(CMD), row({ ...CMD, call_id: "r2", pretty: "ls" })], count);
    await screen.findByTestId("runcmd-card");
    expect(screen.getByTestId("ask-queue")).toHaveTextContent('kit.queueOf:{"index":1,"total":2}');
    await waitFor(() => expect(count).toHaveBeenCalledWith(2));
  });

  it("answering a card takes out that call id and no other", async () => {
    const req = serve([row(CMD), row({ ...CMD, call_id: "r2", pretty: "ls" })]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    fireEvent.click(await screen.findByTestId("runcmd-cancel"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/r1/answer", expect.anything()));
    expect(req.mock.calls.some(([path]) => path === "/approvals/r2/answer")).toBe(false);
  });
});

describe("Always is never taken for the person", () => {
  it("a card that lists Always first still opens on the narrowest choice, and a yes sends that", async () => {
    const req = serve([row({ ...ACT, kind: "app", perm_kind: "app", options: ["always", "task", "conversation"], always_label: "Notes" })]);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    expect(((await screen.findByTestId("action-scope-task")) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByTestId("action-scope-always") as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getByTestId("action-allow"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/a1/answer",
      { method: "POST", body: JSON.stringify({ approve: true, source: "inbox", scope: "task" }) }));
  });
});
