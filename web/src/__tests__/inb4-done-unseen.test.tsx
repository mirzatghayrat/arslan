/** INB4 (v0.1.64): "done, not seen". A green check with a blue dot until the window shows the conversation, then a chat looks as
 *  it does today and a job keeps its check; a project row carries its most urgent conversation (waiting > working > done, not seen). */
import { act, cleanup, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { resolvedLanguage: "en", language: "en" } }) }));
vi.mock("../api/client", () => ({ api: { listConversations: vi.fn(), markConversationSeen: vi.fn(async () => ({ seen_message_id: 9 })) } }));
beforeAll(() => { window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

import { api } from "../api/client";
import ConversationGlyph from "../components/ConversationGlyph";
import Sidebar from "../components/Sidebar";
import { useConversationIndex } from "../hooks/useConversationIndex";
import { metaFrom, type ConversationMeta } from "../lib/conversationMeta";

const setVisibility = (value: "visible" | "hidden") =>
  Object.defineProperty(document, "visibilityState", { value, configurable: true });
afterEach(() => {
  cleanup(); vi.clearAllMocks(); setVisibility("visible");
  vi.mocked(api.markConversationSeen).mockResolvedValue({ seen_message_id: 9 } as never);   // undo a test's own implementation
});
const wait = (ms: number) => act(async () => { await new Promise((r) => setTimeout(r, ms)); });

const m = (state: string, extra: Partial<ConversationMeta> = {}) =>
  ({ kind: "chat", state, origin: "mac", files: 0, ...extra }) as ConversationMeta;

describe("the glyph", () => {
  it("draws done, not seen as a state of its own, and keeps it from the server's list", () => {
    render(<ConversationGlyph meta={m("done_unseen")} />);
    expect(screen.getByRole("img", { name: "sidebar.glyph.done_unseen" })).toBeInTheDocument();
    expect(metaFrom([{ conversation_id: "c", state: "done_unseen" } as never]).c.state).toBe("done_unseen");
  });
});

describe("a project row", () => {
  const threads = [{ id: "a", title: "A" }, { id: "b", title: "B" }, { id: "c", title: "C" }];
  const props = {
    activeThreadId: "", onSelectThread: () => {}, onAddThread: () => {}, activeSection: "arslan" as const,
    onChangeSection: () => {}, onArchiveThread: vi.fn(), onUnarchiveThread: vi.fn(), onDeleteThread: vi.fn(),
    backendStatus: "online" as const, threads, projects: [{ id: "p1", name: "Home" }],
  };
  const meta = (states: string[]) => Object.fromEntries(threads.map((t, i) => [t.id, m(states[i], { projectId: "p1" })]));
  const state = () => within(screen.getByTestId("sidebar-project-p1")).queryByTestId("project-state-p1");

  it("shows its most urgent conversation: waiting, then working, then done, not seen", () => {
    const { rerender } = render(<Sidebar {...props} meta={meta(["done_unseen", "working", "waiting"])} />);
    expect(state()).toHaveAttribute("aria-label", "sidebar.glyph.waiting");
    rerender(<Sidebar {...props} meta={meta(["done_unseen", "working", "idle"])} />);
    expect(state()).toHaveAttribute("aria-label", "sidebar.glyph.working");
    rerender(<Sidebar {...props} meta={meta(["done_unseen", "done", "idle"])} />);
    expect(state()).toHaveAttribute("aria-label", "sidebar.glyph.done_unseen");
    rerender(<Sidebar {...props} meta={meta(["idle", "done", "failed"])} />);
    expect(state()).toBeNull();
  });
});

describe("marking seen", () => {
  const rows = [{ conversation_id: "c1", kind: "chat", state: "done_unseen" }, { conversation_id: "t1", kind: "task", state: "done_unseen" }];

  it("marks the open conversation seen once the window shows it: a chat reads idle, a job done", async () => {
    vi.mocked(api.listConversations).mockResolvedValue(rows as never);
    const { result, rerender } = renderHook(({ section, open }) => useConversationIndex(60_000, section, open),
      { initialProps: { section: "arslan", open: null as string | null } });
    await waitFor(() => expect(result.current.meta.c1?.state).toBe("done_unseen"));
    expect(api.markConversationSeen).not.toHaveBeenCalled();                    // nothing is open
    rerender({ section: "scheduled", open: "c1" });                             // another page shows: c1 is not on screen
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(api.markConversationSeen).not.toHaveBeenCalled();
    rerender({ section: "arslan", open: "c1" });
    await waitFor(() => expect(result.current.meta.c1.state).toBe("idle"));
    expect(api.markConversationSeen).toHaveBeenCalledWith("c1");
    rerender({ section: "arslan", open: "t1" });
    await waitFor(() => expect(result.current.meta.t1.state).toBe("done"));
  });

  it("waits while the window is hidden, and marks it when the window shows again", async () => {
    vi.mocked(api.listConversations).mockResolvedValue(rows as never);
    const { result, rerender } = renderHook(({ open }) => useConversationIndex(60_000, "arslan", open), { initialProps: { open: null as string | null } });
    await waitFor(() => expect(result.current.meta.c1?.state).toBe("done_unseen"));
    setVisibility("hidden");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    rerender({ open: "c1" });
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(api.markConversationSeen).not.toHaveBeenCalled();
    setVisibility("visible");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    await waitFor(() => expect(api.markConversationSeen).toHaveBeenCalledWith("c1"));
  });

  it("tries again on the next poll when marking failed (#589 F3)", async () => {
    vi.mocked(api.listConversations).mockResolvedValue(rows as never);
    vi.mocked(api.markConversationSeen).mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ seen_message_id: 9 } as never);
    const { result } = renderHook(() => useConversationIndex(40, "arslan", "c1"));
    await waitFor(() => expect(api.markConversationSeen).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.meta.c1.state).toBe("idle"));
  });

  it("marks a conversation each time it opens, whatever it reads: a stopped job too (#590 review F1)", async () => {
    vi.mocked(api.listConversations).mockResolvedValue([...rows, { conversation_id: "t2", kind: "task", state: "unfinished" },
      { conversation_id: "c3", kind: "chat", state: "idle" }] as never);
    const { result, rerender } = renderHook(({ open }) => useConversationIndex(60_000, "arslan", open), { initialProps: { open: "t2" as string | null } });
    await waitFor(() => expect(api.markConversationSeen).toHaveBeenCalledWith("t2"));
    rerender({ open: "c3" });
    await waitFor(() => expect(api.markConversationSeen).toHaveBeenCalledWith("c3"));
    rerender({ open: "t2" });                                                   // opened again: marked again
    await waitFor(() => expect(vi.mocked(api.markConversationSeen).mock.calls.filter(([id]) => id === "t2")).toHaveLength(2));
    expect(result.current.meta.t2.state).toBe("unfinished");                    // its own state stays; only done, not seen changes at once
  });

  it("leaves a conversation the server has not listed alone, and marks one with a live card once, not on every poll", async () => {
    vi.mocked(api.listConversations).mockResolvedValue([{ conversation_id: "c4", kind: "chat", state: "waiting" }] as never);
    const { rerender } = renderHook(({ open }) => useConversationIndex(30, "arslan", open), { initialProps: { open: "new-1" as string | null } });
    await act(async () => { await new Promise((r) => setTimeout(r, 120)); });  // a few polls
    expect(api.markConversationSeen).not.toHaveBeenCalled();                    // not listed yet: nothing to mark, so no 404
    rerender({ open: "c4" });
    await act(async () => { await new Promise((r) => setTimeout(r, 150)); });
    expect(api.markConversationSeen).toHaveBeenCalledTimes(1);
  });

  it("marks again when a reply lands while it is open, and when the window shows again", async () => {
    vi.mocked(api.listConversations).mockResolvedValue([{ conversation_id: "c5", kind: "chat", state: "idle" }] as never);
    const { result } = renderHook(() => useConversationIndex(30, "arslan", "c5"));
    await waitFor(() => expect(api.markConversationSeen).toHaveBeenCalledTimes(1));
    vi.mocked(api.listConversations).mockResolvedValue([{ conversation_id: "c5", kind: "chat", state: "done_unseen" }] as never);
    await waitFor(() => expect(vi.mocked(api.markConversationSeen).mock.calls.length).toBeGreaterThanOrEqual(2));   // the reply that landed is seen
    vi.mocked(api.listConversations).mockResolvedValue([{ conversation_id: "c5", kind: "chat", state: "idle" }] as never);
    await waitFor(() => expect(result.current.meta.c5.state).toBe("idle"));
    await wait(80);
    const before = vi.mocked(api.markConversationSeen).mock.calls.length;   // a stale poll may have sent one harmless extra mark
    setVisibility("hidden");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    setVisibility("visible");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    await waitFor(() => expect(vi.mocked(api.markConversationSeen).mock.calls.length).toBe(before + 1));
  });

  it("marks it again after another section showed, since coming back opens it again", async () => {
    vi.mocked(api.listConversations).mockResolvedValue([{ conversation_id: "c6", kind: "chat", state: "idle" }] as never);
    const { rerender } = renderHook(({ section }) => useConversationIndex(60_000, section, "c6"), { initialProps: { section: "arslan" } });
    await waitFor(() => expect(api.markConversationSeen).toHaveBeenCalledTimes(1));
    rerender({ section: "scheduled" });
    rerender({ section: "arslan" });
    await waitFor(() => expect(api.markConversationSeen).toHaveBeenCalledTimes(2));
  });

  it("marks a second reply that lands while the conversation stays open (#589 re-check)", async () => {
    let state = "done_unseen";
    vi.mocked(api.listConversations).mockImplementation(async () => [{ conversation_id: "c7", kind: "chat", state }] as never);
    vi.mocked(api.markConversationSeen).mockImplementation(async () => { state = "idle"; return { seen_message_id: 1 } as never; });
    const { result } = renderHook(() => useConversationIndex(30, "arslan", "c7"));
    await waitFor(() => expect(api.markConversationSeen).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.meta.c7.state).toBe("idle"));
    state = "working"; await wait(120);                                         // the user asks again
    state = "done_unseen"; await wait(200);                                     // the next reply lands while it is open
    expect(api.markConversationSeen).toHaveBeenCalledTimes(2);
    expect(result.current.meta.c7.state).toBe("idle");
  });

  it("marks a second card that waits while the conversation stays open", async () => {
    let state = "waiting";
    vi.mocked(api.listConversations).mockImplementation(async () => [{ conversation_id: "c8", kind: "chat", state }] as never);
    renderHook(() => useConversationIndex(30, "arslan", "c8"));
    await waitFor(() => expect(api.markConversationSeen).toHaveBeenCalledTimes(1));
    state = "working"; await wait(120);                                         // answered, and it carries on
    state = "waiting"; await wait(200);                                         // a second card
    expect(api.markConversationSeen).toHaveBeenCalledTimes(2);
  });
});
