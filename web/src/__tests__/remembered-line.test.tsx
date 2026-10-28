/** D1 (0.1.55): a remembered fact is one quiet line with Undo — never an Arslan reply.
 *  INB2 (v0.1.64): a sensitive one from the user's own present, clean turn asks once, with two buttons bound to its
 *  proposal; any other that waits says why and points to Memory's "To sort" list. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";

vi.mock("react-i18next", () => {
  const t = (key: string, opts?: Record<string, unknown>) =>
    (opts?.text ? `${key}:${opts.text}${opts.reason ? `|${opts.reason}` : ""}` : key);
  return { useTranslation: () => ({ t, i18n: { resolvedLanguage: "zh" } }) };
});

import RememberedLine, { toUser } from "../components/RememberedLine";
import * as client from "../api/client";
import { companionApi } from "../api/companion";
import { toUiMessages } from "../api/adapters";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { OPEN_SECTION_EVENT } from "../lib/sections";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const fact = (content: string, extra: Record<string, unknown> = {}) =>
  ({ type: "fact_saved", content, sensitive: false, entry_id: `e-${content.length}`, version: 1, ...extra }) as never;

describe("what Arslan remembered after a turn", () => {
  it("several facts of one turn become ONE item, rendered as a line, not a bubble", () => {
    useArslanStore.setState(initialArslanState());
    const store = useArslanStore.getState();
    store.handleFrame({ type: "message", role: "arslan", content: "好的" } as never);
    store.handleFrame(fact("用户关注 Hermes"));
    store.handleFrame(fact("用户在做 Sluice"));
    const items = useArslanStore.getState().items;
    const facts = items.filter((i) => i.kind === "fact");
    expect(facts).toHaveLength(1);
    expect(facts[0].facts?.map((f) => f.content)).toEqual(["用户关注 Hermes", "用户在做 Sluice"]);
    const [message] = toUiMessages(facts);
    expect(message.remembered).toHaveLength(2);
    expect(message.remembered?.[0]).toMatchObject({ entryId: "e-11", version: 1, status: "active" });
  });

  it("speaks to the user, and Undo deletes exactly those entries at their versions", async () => {
    const req = vi.spyOn(client, "request").mockResolvedValue({} as never);
    render(<RememberedLine facts={[
      { content: "用户关注 Hermes", sensitive: false, entryId: "a", version: 1, status: "active" },
      { content: "用户在做 Sluice", sensitive: false, entryId: "b", version: 2, status: "active" },
    ]} />);
    expect(screen.getByTestId("remembered-line")).toHaveTextContent("chat.remembered:你关注 Hermes · 你在做 Sluice");
    fireEvent.click(screen.getByText("chat.rememberedUndo"));
    await waitFor(() => expect(screen.getByText("chat.rememberedUndone")).toBeInTheDocument());
    expect(req.mock.calls.map((c) => c[0])).toEqual(["/memory/entries/a?expected_version=1",
                                                     "/memory/entries/b?expected_version=2"]);
  });

  it("a fact that waits carries its proposal and why it waits from the frame (INB2)", () => {
    useArslanStore.setState(initialArslanState());
    const store = useArslanStore.getState();
    store.handleFrame({ type: "message", role: "arslan", content: "好的" } as never);
    store.handleFrame({ type: "memory_proposed", content: "用户的孩子周三有钢琴课", sensitive: true, entry_id: "k",
      version: 1, proposal_id: 11, reason: "sensitive" } as never);
    const [message] = toUiMessages(useArslanStore.getState().items.filter((i) => i.kind === "fact"));
    expect(message.remembered?.[0]).toMatchObject({ status: "proposed", entryId: "k", version: 1, proposalId: 11,
                                                    reason: "sensitive" });
  });

  it("one that waits for any other reason says why and points to Memory; no keep in the chat (INB2)", () => {
    const opened: string[] = [];
    const listen = (e: Event) => opened.push((e as CustomEvent<string>).detail);
    window.addEventListener(OPEN_SECTION_EVENT, listen);
    render(<RememberedLine facts={[
      { content: "用户在做骑行网站", sensitive: false, status: "proposed", proposalId: 4, reason: "external_seen" },
      { content: "用户每周一看周报", sensitive: false, status: "proposed", proposalId: 6, reason: "not_present" },
      { content: "用户的家人周末来", sensitive: true, status: "proposed", proposalId: 5, reason: "external_seen" },
      // A frame from before INB2: no proposal, no reason. It never gets the buttons.
      { content: "用户血压偏高", sensitive: true, status: "proposed" },
    ]} />);
    expect(screen.getAllByTestId("memory-waits").map((line) => line.textContent)).toEqual([
      "chat.memoryWaits:你在做骑行网站 · 你的家人周末来|chat.memoryWhy_external_seenchat.memorySeeInMemory",
      "chat.memoryWaits:你每周一看周报|chat.memoryWhy_not_presentchat.memorySeeInMemory",
      "chat.memoryWaits:你血压偏高|chat.memoryWhy_sensitivechat.memorySeeInMemory",
    ]);
    expect(screen.queryByText("pendingMemory.keepLocal")).toBeNull();
    expect(screen.queryByText("chat.rememberedUndo")).toBeNull();
    fireEvent.click(screen.getAllByText("chat.memorySeeInMemory")[0]);
    window.removeEventListener(OPEN_SECTION_EVENT, listen);
    expect(opened).toEqual(["brain"]);
  });

  it("a sensitive one from the user's own clean turn asks once: each pair of buttons answers exactly its proposal, for this Mac only (INB2)", async () => {
    const resolve = vi.spyOn(companionApi, "resolveProposal").mockResolvedValue({} as never);
    render(<RememberedLine facts={[
      { content: "用户关注 Hermes", sensitive: false, entryId: "a", version: 1, status: "active" },
      { content: "用户的孩子周三有钢琴课", sensitive: true, entryId: "k", version: 1, status: "proposed", proposalId: 11,
        reason: "sensitive" },
      { content: "用户的父母住在老家", sensitive: true, entryId: "p", version: 1, status: "proposed", proposalId: 12,
        reason: "sensitive" },
    ]} />);
    expect(screen.getByTestId("memory-ask-11")).toHaveTextContent("chat.memoryAsk:你的孩子周三有钢琴课");
    fireEvent.click(within(screen.getByTestId("memory-ask-11")).getByText("pendingMemory.keepLocal"));
    await waitFor(() => expect(screen.getByTestId("memory-ask-11")).toHaveTextContent("chat.memoryKeptLocal:你的孩子周三有钢琴课"));
    expect(resolve.mock.calls).toEqual([[11, true, true, false]]);
    expect(within(screen.getByTestId("memory-ask-11")).queryByRole("button")).toBeNull();      // asked once
    fireEvent.click(within(screen.getByTestId("memory-ask-12")).getByText("pendingMemory.drop"));
    await waitFor(() => expect(screen.getByTestId("memory-ask-12")).toHaveTextContent("chat.memorySkipped"));
    expect(resolve.mock.calls).toEqual([[11, true, true, false], [12, false, false, false]]);
    expect(screen.getByText("chat.rememberedUndo")).toBeInTheDocument();          // the one that took effect keeps Undo
  });

  it("an answer the server refuses (changed since, or answered in Memory) points to Memory and asks no more (INB2)", async () => {
    vi.spyOn(companionApi, "resolveProposal").mockRejectedValue(new client.ApiError("memory_version_conflict", 409));
    const opened: string[] = [];
    const listen = (e: Event) => opened.push((e as CustomEvent<string>).detail);
    window.addEventListener(OPEN_SECTION_EVENT, listen);
    render(<RememberedLine facts={[{ content: "用户的孩子周三有钢琴课", sensitive: true, status: "proposed", proposalId: 11,
                                     reason: "sensitive" }]} />);
    fireEvent.click(screen.getByText("pendingMemory.keepLocal"));
    fireEvent.click(await screen.findByText("chat.rememberedChanged"));
    window.removeEventListener(OPEN_SECTION_EVENT, listen);
    expect(opened).toEqual(["brain"]);
    expect(screen.queryByText("pendingMemory.keepLocal")).toBeNull();
    expect(screen.queryByText("pendingMemory.drop")).toBeNull();
  });

  it("a later change is not overwritten: the line sends you to Memory", async () => {
    vi.spyOn(client, "request").mockRejectedValue(new Error("409"));
    render(<RememberedLine facts={[{ content: "x", sensitive: false, entryId: "a", version: 1, status: "active" }]} />);
    fireEvent.click(screen.getByText("chat.rememberedUndo"));
    await waitFor(() => expect(screen.getByText("chat.rememberedChanged")).toBeInTheDocument());
  });

  it("third person becomes second person only at the start", () => {
    expect(toUser("用户关注 agent")).toBe("你关注 agent");
    expect(toUser("ユーザーは短い答えが好き")).toBe("あなたは短い答えが好き");
    expect(toUser("The user prefers short answers")).toBe("The user prefers short answers");
    expect(toUser("喜欢用户界面简洁")).toBe("喜欢用户界面简洁");
  });
});
