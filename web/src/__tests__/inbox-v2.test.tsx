/** 0.1.55 §12: the Inbox is everything waiting for the user's decision — cards to
 *  approve (answered here, over HTTP), and memory waiting for an OK (three sources, one list). */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import * as client from "../api/client";
import { companionApi } from "../api/companion";
import { lessonsApi } from "../api/lessons";
import InboxApprovals from "../components/proactive/InboxApprovals";
import InboxMemory from "../components/proactive/InboxMemory";
import { loadPendingMemory } from "../lib/pendingMemory";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const ask = {
  call_id: "c1", conversation_id: "conv-9", opened_at: 1000, expires_at: 1300,
  frame: { type: "propose_run_command", call_id: "c1", pretty: "git push", reason: "pushes to a remote" },
};

describe("Approve now", () => {
  it("lists a waiting card from any conversation and answers it over HTTP, as the Inbox", async () => {
    const req = vi.spyOn(client, "request").mockImplementation(async (path: string) =>
      (path === "/approvals/pending" ? [ask] : { ok: true }) as never);
    const opened = vi.fn();
    render(<InboxApprovals onOpenConversation={opened} />);
    expect(await screen.findByTestId("runcmd-card")).toBeInTheDocument();
    expect(screen.getByTestId("ask-risk")).toHaveTextContent("pushes to a remote");
    fireEvent.click(screen.getByText("kit.seeContext"));
    expect(opened).toHaveBeenCalledWith("conv-9");
    fireEvent.click(screen.getByTestId("runcmd-run"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/c1/answer",
      { method: "POST", body: JSON.stringify({ approve: true, source: "inbox" }) }));
  });

  it("a card it cannot answer outside the chat is not shown; nothing waiting shows nothing", async () => {
    vi.spyOn(client, "request").mockResolvedValue([{ ...ask, frame: { type: "propose_connect_mcp", call_id: "m" } }] as never);
    const count = vi.fn();
    const { container } = render(<InboxApprovals onOpenConversation={() => {}} onCount={count} />);
    await waitFor(() => expect(count).toHaveBeenCalledWith(0));
    expect(container).toBeEmptyDOMElement();
  });
});

describe("memory waiting for your OK", () => {
  it("merges the three sources, and one failing source hides nothing else", async () => {
    vi.spyOn(companionApi, "proposals").mockResolvedValue([{ id: 1, target_id: "e1", target_version: 1, reason: "",
      candidate: null, entry: { content: "体检报告里的血压数据", sensitivity: "sensitive", created_at: "2026-10-06T00:00:00Z" } }] as never);
    vi.spyOn(client.api, "listMemoryProposals").mockRejectedValue(new Error("down"));
    vi.spyOn(lessonsApi, "list").mockResolvedValue([
      { id: 7, status: "proposed", text: "读大表格 → 先看表头", created_at: "2026-10-07T00:00:00Z" },
      { id: 8, status: "active", text: "not waiting", created_at: "2026-10-07T00:00:00Z" }] as never);
    const items = await loadPendingMemory(((k: string) => k) as never);
    expect(items.map((i) => [i.source, i.text, i.sensitive])).toEqual([
      ["lesson", "读大表格 → 先看表头", false], ["memory", "体检报告里的血压数据", true]]);
  });

  it("a sensitive one is kept for local models only, with the sensitivity acknowledged", async () => {
    vi.spyOn(companionApi, "proposals").mockResolvedValue([{ id: 3, target_id: "e3", target_version: 1, reason: "",
      candidate: null, entry: { content: "血压", sensitivity: "sensitive", created_at: "2026-10-06T00:00:00Z" } }] as never);
    vi.spyOn(client.api, "listMemoryProposals").mockResolvedValue([]);
    vi.spyOn(lessonsApi, "list").mockResolvedValue([]);
    const resolve = vi.spyOn(companionApi, "resolveProposal").mockResolvedValue({} as never);
    render(<InboxMemory />);
    fireEvent.click(await screen.findByText("pendingMemory.keepLocal"));
    await waitFor(() => expect(resolve).toHaveBeenCalledWith(3, true, true, false));
  });
});
