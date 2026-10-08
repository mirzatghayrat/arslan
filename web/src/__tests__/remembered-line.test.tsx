/** D1 (0.1.55): a remembered fact is one quiet line with Undo — never an Arslan reply. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, unknown>) => (opts?.text ? `${key}:${opts.text}` : key),
    i18n: { resolvedLanguage: "zh" } }),
}));

import RememberedLine, { toUser } from "../components/RememberedLine";
import * as client from "../api/client";
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

  it("a fact that waits points to Memory instead of offering Undo", () => {
    const opened: string[] = [];
    const listen = (e: Event) => opened.push((e as CustomEvent<string>).detail);
    window.addEventListener(OPEN_SECTION_EVENT, listen);
    render(<RememberedLine facts={[{ content: "用户血压偏高", sensitive: true, status: "proposed" }]} />);
    expect(screen.queryByText("chat.rememberedUndo")).toBeNull();
    fireEvent.click(screen.getByText("chat.rememberedReview"));
    window.removeEventListener(OPEN_SECTION_EVENT, listen);
    expect(opened).toEqual(["brain"]);
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
