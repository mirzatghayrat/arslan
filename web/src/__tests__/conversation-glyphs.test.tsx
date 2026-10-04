/** Phone v2, Mac side: each conversation in the sidebar shows what it is and how it stands, the phone's
 *  own conversation is "Remote" (pinned first), tasks started from the iPhone carry a phone mark, and
 *  the list stays fresh so a task handed over from the phone appears without a restart. */
import { render, screen, within, act, renderHook } from "@testing-library/react";
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import Sidebar from "../components/Sidebar";
import ConversationGlyph from "../components/ConversationGlyph";
import { metaFrom, remoteFirst, type ConversationMeta } from "../lib/conversationMeta";
import { threadDisplayTitle } from "../lib/threadTitles";

const listConversations = vi.fn();
vi.mock("../api/client", () => ({ api: { listConversations: () => listConversations() } }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${o.done}/${o.total}` : k) }),
}));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

const meta = (m: Partial<ConversationMeta>): ConversationMeta => ({ kind: "chat", state: "idle", origin: "mac", files: 0, ...m });

describe("conversation glyphs", () => {
  it.each([
    [meta({ kind: "remote" }), "sidebar.glyph.remote"],
    [meta({ kind: "task", state: "working", job: { id: "j", step: "s", done: 1, total: 3 } }), "sidebar.glyph.progress:1/3"],
    [meta({ kind: "task", state: "working" }), "sidebar.glyph.working"],
    [meta({ kind: "chat", state: "waiting" }), "sidebar.glyph.waiting"],
    [meta({ kind: "remote", state: "waiting" }), "sidebar.glyph.waiting"],
    [meta({ kind: "task", state: "done" }), "sidebar.glyph.done"],
    [meta({ kind: "task", state: "failed" }), "sidebar.glyph.failed"],
    [meta({ kind: "scheduled" }), "sidebar.glyph.scheduled"],
  ])("%o reads as %s", (m, label) => {
    render(<ConversationGlyph meta={m} />);
    expect(screen.getByRole("img", { name: label })).toBeTruthy();
  });

  it("a plain conversation keeps the quiet speech bubble, with nothing to announce", () => {
    const { container } = render(<ConversationGlyph meta={meta({})} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("a running task's ring fills by its progress", () => {
    const { container } = render(<ConversationGlyph meta={meta({ kind: "task", state: "working", job: { id: "j", step: "", done: 2, total: 4 } })} />);
    const arc = container.querySelectorAll("circle")[1];
    const [filled, whole] = arc.getAttribute("stroke-dasharray")!.split(" ").map(Number);
    expect(filled / whole).toBeCloseTo(0.5, 2);
  });
});

describe("the server's conversation list, as sidebar data", () => {
  it("keeps only known kinds and states, and names the phone's conversation", () => {
    const got = metaFrom([
      { conversation_id: "pocket", title: "Remote", message_count: 3 },
      { conversation_id: "task-1", title: "t", message_count: 1, kind: "task", state: "working", origin: "phone",
        job: { id: "j", step: "run_command npm test", done: 0, total: 2 } },
      { conversation_id: "odd", title: "o", message_count: 1, kind: "weird", state: "exploded", origin: "?" },
    ]);
    expect(got.pocket.kind).toBe("remote");
    expect(got["task-1"]).toMatchObject({ kind: "task", state: "working", origin: "phone" });
    expect(got.odd).toMatchObject({ kind: "chat", state: "idle", origin: "mac" });
  });

  it("puts Remote first and leaves the rest in order", () => {
    const threads = [{ id: "a" }, { id: "pocket" }, { id: "b" }];
    expect(remoteFirst(threads, {}).map(t => t.id)).toEqual(["pocket", "a", "b"]);
  });

  it("titles the phone's conversation Remote, not after its first message", () => {
    const t = (k: string) => k;
    expect(threadDisplayTitle({ id: "pocket", title: "在干嘛" }, t)).toBe("sidebar.remote");
    expect(threadDisplayTitle({ id: "x", title: "在干嘛" }, t, "remote")).toBe("sidebar.remote");
    expect(threadDisplayTitle({ id: "x", title: "在干嘛" }, t, "chat")).toBe("在干嘛");
  });
});

describe("the sidebar with conversation data", () => {
  const props = {
    threads: [{ id: "chat-1", title: "护照材料" }, { id: "task-1", title: "Q3 报告" }, { id: "pocket", title: "在干嘛" }],
    activeThreadId: "chat-1", onSelectThread: () => {}, onAddThread: () => {}, activeSection: "arslan" as const,
    onChangeSection: () => {}, onDistillThread: vi.fn(), onArchiveThread: vi.fn(), onUnarchiveThread: vi.fn(),
    onDeleteThread: vi.fn(), backendStatus: "online" as const,
    meta: { pocket: meta({ kind: "remote", origin: "phone" }),
            "task-1": meta({ kind: "task", state: "working", origin: "phone", job: { id: "j", step: "", done: 1, total: 2 } }),
            "chat-1": meta({}) },
  } as any;

  it("pins Remote first, under its own name, and marks what the phone started", () => {
    render(<Sidebar {...props} />);
    const list = screen.getByRole("region", { name: "workspace.recentConversations" });
    const rows = within(list).getAllByRole("button").filter(b => b.id.startsWith("active-thread-btn-"));
    expect(rows.map(r => r.id)).toEqual(["active-thread-btn-pocket", "active-thread-btn-chat-1", "active-thread-btn-task-1"]);
    expect(within(rows[0]).getByText("sidebar.remote")).toBeTruthy();
    expect(within(rows[0]).queryByLabelText("sidebar.fromPhone")).toBeNull();      // Remote IS the phone
    expect(within(rows[2]).getByLabelText("sidebar.fromPhone")).toBeTruthy();
    expect(within(rows[2]).getByRole("img", { name: "sidebar.glyph.progress:1/2" })).toBeTruthy();
    expect(within(rows[1]).queryByLabelText("sidebar.fromPhone")).toBeNull();
  });
});

describe("the conversation index stays fresh", () => {
  beforeEach(() => { vi.useFakeTimers(); listConversations.mockReset(); });
  afterEach(() => { vi.useRealTimers(); });

  it("polls, and keeps the last good list when a poll fails", async () => {
    const { useConversationIndex } = await import("../hooks/useConversationIndex");
    listConversations
      .mockResolvedValueOnce([{ conversation_id: "a", title: "a", message_count: 1, state: "working", kind: "task" }])
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce([{ conversation_id: "a", title: "a", message_count: 1, state: "done", kind: "task" },
                              { conversation_id: "task-new", title: "from the phone", message_count: 1, kind: "task", origin: "phone" }]);
    const { result } = renderHook(() => useConversationIndex(1000));
    await act(async () => { await Promise.resolve(); });
    expect(result.current.meta.a.state).toBe("working");
    await act(async () => { vi.advanceTimersByTime(1000); await Promise.resolve(); });
    expect(result.current.meta.a.state).toBe("working");
    await act(async () => { vi.advanceTimersByTime(1000); await Promise.resolve(); });
    expect(result.current.meta.a.state).toBe("done");
    expect(result.current.rows.map(r => r.conversation_id)).toContain("task-new");
  });
});
