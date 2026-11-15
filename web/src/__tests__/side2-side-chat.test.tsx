/**
 * SIDE-2 (v0.1.64, card docs/plans/0164/SIDE-side-chat.md): the web side of side chats. A selection in a reply shows a
 * bar; "Start a side chat" branches at that reply with the selection waiting as a quote, and nothing is sent until the
 * user sends; "Bring back to main" fills the main input and sends nothing; "+" starts one at the newest message; a
 * closed tab keeps its side chat, which Overview lists, reopens and deletes; the outside-content line shows only on one
 * that started marked (the user, 2026-11-11, A and B).
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k),
    i18n: { resolvedLanguage: "en", language: "en" } }),
}));
const { files, jobsApi, mcp, client, conv, sides, ws } = vi.hoisted(() => ({
  files: { list: vi.fn(), read: vi.fn(), stat: vi.fn(), open: vi.fn(), reveal: vi.fn(), home: vi.fn(), conversationFiles: vi.fn(),
    changes: vi.fn(), repoChanges: vi.fn() },
  jobsApi: { list: vi.fn(), stop: vi.fn() },
  mcp: { listMcpServers: vi.fn(), reconnectMcpServer: vi.fn() },
  client: { fetchProviderModels: vi.fn(), updateProviderConfig: vi.fn(),
    api: { runCheckpoint: vi.fn(), undoTurn: vi.fn(), extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } },
  conv: { get: vi.fn(), set: vi.fn(), clear: vi.fn() },
  sides: { list: vi.fn(), create: vi.fn(), remove: vi.fn() },
  ws: { handlers: new Map<string, (m: unknown) => void>(), sends: [] as { path: string; frame: unknown }[] },
}));
vi.mock("../api/files", () => ({ filesApi: files }));
vi.mock("../api/tasks", () => ({ backgroundJobsApi: jobsApi }));
vi.mock("../api/mcp", () => mcp);
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), ...client }));
vi.mock("../api/conversationModel", () => ({ conversationModelApi: conv }));
vi.mock("../api/lessons", () => ({ lessonsApi: { folderRules: vi.fn().mockRejectedValue(new Error("none")) } }));
vi.mock("../api/sideChats", () => ({ sideChatsApi: sides }));
vi.mock("../components/BrowserReader", () => ({ default: () => <div data-testid="browser-reader" /> }));
// A side chat's tab talks to its own conversation's socket; every frame it sends is recorded here.
vi.mock("../hooks/useWebSocket", () => ({
  useWebSocket: (path: string, onMessage: (m: unknown) => void) => {
    ws.handlers.set(path, onMessage);
    return { send: (frame: unknown) => ws.sends.push({ path, frame }), reconnecting: false, setLastMessageId: () => {} };
  },
}));

import type { SideChat } from "../api/sideChats";
import type { Message } from "../types";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { useSettingsStore } from "../stores/settingsStore";
import { useWorkbench } from "../stores/workbenchStore";
import OrchestratorChat from "../components/OrchestratorChat";
import Workbench from "../components/workbench/Workbench";
import { composerDrafts } from "../lib/composerDrafts";

const chat = (id: string, extra: Partial<SideChat> = {}): SideChat => ({ conversation_id: id, parent_id: "c1", branch_message_id: 42,
  outside_at_start: false, created_at: "2026-11-15T10:00:00", message_count: 0, last_at: null, ...extra });
const REPLY = "Your drive holds the library plus about a year of changes.";
const history: Message[] = [
  { id: "41", sender: "user", senderName: "You", senderAvatar: "", text: "How long will the drive last?", timestamp: "10:00" },
  { id: "42", sender: "arslan", senderName: "Arslan", senderAvatar: "🦁", text: REPLY, timestamp: "10:01" },
];
const onSendMessage = vi.fn();
const mountChat = () => render(<OrchestratorChat chatHistory={history} setChatHistory={vi.fn()} spawns={[]} currentStyle="quartz"
  setCurrentStyle={vi.fn()} activeThread={null} conversationId="c1" onSendMessage={onSendMessage} />);
const mountBench = (temporary = false) => render(<Workbench conversationId="c1" taskId={null} temporary={temporary} />);
const mainInput = () => document.getElementById("chat-message-input") as HTMLTextAreaElement;
const sent = (path: string) => ws.sends.filter((s) => s.path === path).map((s) => s.frame);

/** Select `word` inside the reply with message id `replyId`, as a mouse would, and let go. */
function select(replyId: string, word: string) {
  const reply = document.querySelector(`[data-reply-id="${replyId}"]`)!;
  const walker = document.createTreeWalker(reply, NodeFilter.SHOW_TEXT);
  let node: Node | null;
  while ((node = walker.nextNode()) && !node.textContent!.includes(word)) { /* next */ }
  const at = node!.textContent!.indexOf(word);
  const range = document.createRange();
  range.setStart(node!, at);
  range.setEnd(node!, at + word.length);
  const sel = window.getSelection()!;
  sel.removeAllRanges();
  sel.addRange(range);
  fireEvent.mouseUp(document);
}

beforeAll(() => { Element.prototype.scrollIntoView = vi.fn(); });
beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  useWorkbench.setState({ open: true, tab: "overview", reader: null, folder: null, expanded: false, sides: {}, openSides: {}, sideQuotes: {} });
  useSettingsStore.setState({ settings: { phone_bridge_enabled: false } } as never);
  files.home.mockResolvedValue({ path: null, project: null });
  files.conversationFiles.mockResolvedValue({ files: [] });
  files.changes.mockResolvedValue({ turns: [] });
  files.repoChanges.mockResolvedValue({ repo: null });
  jobsApi.list.mockResolvedValue({ jobs: [] });
  mcp.listMcpServers.mockResolvedValue([]);
  conv.get.mockResolvedValue({ choice: null });
  client.fetchProviderModels.mockResolvedValue({ models: [] });
  // The server as SIDE-1 has it: what was made is listed, oldest first.
  const made: SideChat[] = [];
  sides.create.mockImplementation(async () => { const c = chat(`side-${made.length + 1}`); made.push(c); return c; });
  sides.list.mockImplementation(async () => [...made]);
  sides.remove.mockResolvedValue({});
  composerDrafts.clear();
  ws.handlers.clear();
  ws.sends.length = 0;
});
afterEach(() => { window.getSelection()?.removeAllRanges(); cleanup(); vi.clearAllMocks(); });

describe("the selection bar", () => {
  it("shows over a selection inside one of Arslan's replies, with Start a side chat and Reply", () => {
    mountChat();
    expect(screen.queryByTestId("selection-bar")).toBeNull();
    select("42", "about a year");
    const bar = screen.getByTestId("selection-bar");
    expect(within(bar).getByTestId("selection-start-side")).toHaveTextContent("sideChat.start");
    expect(within(bar).getByTestId("selection-reply")).toHaveTextContent("sideChat.reply");
  });

  it("does not show for a selection in the user's own message", () => {
    mountChat();
    const own = screen.getByText("How long will the drive last?");
    const range = document.createRange();
    range.selectNodeContents(own);
    window.getSelection()!.addRange(range);
    fireEvent.mouseUp(document);
    expect(screen.queryByTestId("selection-bar")).toBeNull();
  });

  it("Reply quotes the selection into the main input and sends nothing", () => {
    mountChat();
    select("42", "about a year");
    fireEvent.click(screen.getByTestId("selection-reply"));
    expect(mainInput().value).toBe("> about a year\n\n");
    expect(onSendMessage).not.toHaveBeenCalled();
  });
});

describe("Start a side chat", () => {
  it("POSTs with the reply's id as the branch, opens a tab with the quote in its input, and sends nothing", async () => {
    mountChat();
    mountBench();
    select("42", "about a year");
    fireEvent.click(screen.getByTestId("selection-start-side"));
    await waitFor(() => expect(sides.create).toHaveBeenCalledWith("c1", 42));
    const tab = await screen.findByTestId("workbench-side-tab-side-1");
    expect(tab).toHaveAttribute("aria-selected", "true");
    expect(tab).toHaveTextContent('sideChat.tab:{"n":1}');
    expect(screen.getByTestId("side-chat-tab")).toBeInTheDocument();
    expect(screen.getByTestId("side-quote")).toHaveTextContent("about a year");
    expect(sent("/ws/arslan/side-1")).toEqual([]);                    // nothing goes out by itself
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it("sends the quote and the question only when the user sends", async () => {
    useWorkbench.getState().startSide("c1", 42, "about a year");
    mountBench();
    const input = await screen.findByTestId("side-input");
    fireEvent.change(input, { target: { value: "Most of it is video. Still a year?" } });
    expect(sent("/ws/arslan/side-1")).toEqual([]);
    fireEvent.click(screen.getByTestId("side-send"));
    expect(sent("/ws/arslan/side-1")).toEqual([{ type: "user_message", content: "> about a year\n\nMost of it is video. Still a year?" }]);
    expect(screen.queryByTestId("side-quote")).toBeNull();
  });

  it("streams the reply into the tab", async () => {
    await useWorkbench.getState().startSide("c1", 42);
    mountBench();
    const push = ws.handlers.get("/ws/arslan/side-1")!;
    act(() => { push({ type: "history", messages: [] }); push({ type: "stream_start" }); push({ type: "stream_chunk", content: "Roughly" }); });
    expect(screen.getByTestId("side-streaming")).toHaveTextContent("Roughly");
    act(() => { push({ type: "stream_chunk", content: " a year." }); push({ type: "stream_end", message_id: 7 }); });
    expect(screen.queryByTestId("side-streaming")).toBeNull();
    expect(screen.getByTestId("side-reply")).toHaveTextContent("Roughly a year.");
  });
});

describe("Bring back to main", () => {
  it("puts the side chat's reply into the main input as a quote and sends nothing anywhere", async () => {
    await useWorkbench.getState().startSide("c1", 42);
    mountChat();
    mountBench();
    act(() => ws.handlers.get("/ws/arslan/side-1")!({ type: "history", messages: [
      { message_id: 5, role: "user", content: "Why a year?" },
      { message_id: 6, role: "arslan", content: "At 100 GB a month, 1.2 TB lasts a year." },
    ] }));
    fireEvent.click(screen.getByTestId("side-bring-back"));
    expect(mainInput().value).toBe("> At 100 GB a month, 1.2 TB lasts a year.\n\n");
    expect(onSendMessage).not.toHaveBeenCalled();
    expect(ws.sends).toEqual([]);
  });
});

describe('"+"', () => {
  it("starts a blank side chat at the newest message in one click: a POST with no branch", async () => {
    mountBench();
    fireEvent.click(screen.getByTestId("workbench-new-side"));
    await waitFor(() => expect(sides.create).toHaveBeenCalledTimes(1));
    expect(sides.create.mock.calls[0][0]).toBe("c1");
    expect(sides.create.mock.calls[0][1] ?? null).toBeNull();
    expect(await screen.findByTestId("workbench-side-tab-side-1")).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByTestId("side-quote")).toBeNull();
  });

  it("is not offered in a temporary conversation", () => {
    mountBench(true);
    expect(screen.queryByTestId("workbench-new-side")).toBeNull();
  });
});

describe("closing, Overview's list, reopening and deleting", () => {
  it("closing the selected tab falls back to Overview, and the side chat is still listed there, closed", async () => {
    await useWorkbench.getState().startSide("c1", 42);
    mountBench();
    fireEvent.click(screen.getByTestId("workbench-side-close-side-1"));
    expect(screen.queryByTestId("workbench-side-tab-side-1")).toBeNull();
    expect(screen.getByTestId("workbench-tab-overview")).toHaveAttribute("aria-selected", "true");
    expect(useWorkbench.getState()).toMatchObject({ open: true, tab: "overview" });
    const row = await screen.findByTestId("overview-side-side-1");
    expect(row).toHaveTextContent('sideChat.tab:{"n":1}');
    expect(row).toHaveTextContent("sideChat.closed");
    expect(sides.remove).not.toHaveBeenCalled();                       // closing is not deleting
  });

  it("closing a tab that isn't selected leaves the selected tab alone", async () => {
    await useWorkbench.getState().startSide("c1", 42);
    await useWorkbench.getState().startSide("c1", 42);
    mountBench();
    fireEvent.click(screen.getByTestId("workbench-side-close-side-1"));
    expect(screen.getByTestId("workbench-side-tab-side-2")).toHaveAttribute("aria-selected", "true");
  });

  it("lists the conversation's side chats from GET, and a row reopens its tab", async () => {
    sides.list.mockResolvedValue([chat("side-a"), chat("side-b")]);
    mountBench();
    await waitFor(() => expect(sides.list).toHaveBeenCalledWith("c1"));
    const rows = await screen.findAllByTestId("overview-side-open");
    expect(rows.map((r) => r.textContent)).toEqual(['sideChat.tab:{"n":1}sideChat.closed', 'sideChat.tab:{"n":2}sideChat.closed']);
    fireEvent.click(rows[1]);
    expect(screen.getByTestId("workbench-side-tab-side-b")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("side-chat-tab")).toBeInTheDocument();
  });

  it("deletes one side chat only after a confirm, naming it as a side chat", async () => {
    sides.list.mockResolvedValue([chat("side-a"), chat("side-b")]);
    mountBench();
    const row = await screen.findByTestId("overview-side-side-a");
    fireEvent.click(within(row).getByTestId("overview-side-delete"));
    expect(sides.remove).not.toHaveBeenCalled();
    fireEvent.click(within(row).getByTestId("overview-side-confirm-delete"));
    await waitFor(() => expect(sides.remove).toHaveBeenCalledWith("side-a"));
    await waitFor(() => expect(screen.queryByTestId("overview-side-side-a")).toBeNull());
    expect(screen.getByTestId("overview-side-side-b")).toBeInTheDocument();
  });
});

describe("the outside-content line (the user, 2026-11-11, B)", () => {
  it("shows only in a side chat that started marked", async () => {
    sides.list.mockResolvedValue([chat("side-clean"), chat("side-marked", { outside_at_start: true })]);
    mountBench();
    const rows = await screen.findAllByTestId("overview-side-open");
    fireEvent.click(rows[0]);
    expect(screen.getByTestId("side-chat-tab")).toBeInTheDocument();
    expect(screen.queryByTestId("side-outside")).toBeNull();
    fireEvent.click(screen.getByTestId("workbench-tab-overview"));
    fireEvent.click((await screen.findAllByTestId("overview-side-open"))[1]);
    expect(screen.getByTestId("side-outside")).toHaveTextContent("sideChat.outside");
  });
});

describe("the client calls", () => {
  it("POSTs a branch only when there is one, and deletes with ?side_chat=true", async () => {
    const { sideChatsApi } = await vi.importActual<typeof import("../api/sideChats")>("../api/sideChats");
    const fetch = vi.fn(async (_url: string, init: RequestInit) => init.method === "DELETE"
      ? new Response(null, { status: 204 }) : new Response(JSON.stringify(chat("side-1")), { status: 201 }));
    vi.stubGlobal("fetch", fetch);
    try {
      await sideChatsApi.create("c1", 42);
      await sideChatsApi.create("c1");
      await sideChatsApi.remove("side-1");
      const [[u1, i1], [u2, i2], [u3, i3]] = fetch.mock.calls as [string, RequestInit][];
      expect(u1).toMatch(/\/conversations\/c1\/side-chats$/);
      expect([i1.method, JSON.parse(i1.body as string)]).toEqual(["POST", { branch_message_id: 42 }]);
      expect([u2, i2.method, JSON.parse(i2.body as string)]).toEqual([u1, "POST", {}]);
      expect(u3).toMatch(/\/conversations\/side-1\?side_chat=true$/);
      expect(i3.method).toBe("DELETE");
    } finally { vi.unstubAllGlobals(); }
  });
});
