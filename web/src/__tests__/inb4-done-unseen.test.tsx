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
afterEach(() => { cleanup(); vi.clearAllMocks(); setVisibility("visible"); });

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
    const { result, rerender } = renderHook(({ open }) => useConversationIndex(60_000, open), { initialProps: { open: null as string | null } });
    await waitFor(() => expect(result.current.meta.c1?.state).toBe("done_unseen"));
    expect(api.markConversationSeen).not.toHaveBeenCalled();                    // nothing is open
    rerender({ open: "c1" });
    await waitFor(() => expect(result.current.meta.c1.state).toBe("idle"));
    expect(api.markConversationSeen).toHaveBeenCalledWith("c1");
    rerender({ open: "t1" });
    await waitFor(() => expect(result.current.meta.t1.state).toBe("done"));
  });

  it("waits while the window is hidden, and marks it when the window shows again", async () => {
    vi.mocked(api.listConversations).mockResolvedValue(rows as never);
    const { result, rerender } = renderHook(({ open }) => useConversationIndex(60_000, open), { initialProps: { open: null as string | null } });
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
});
