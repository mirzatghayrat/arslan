import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { toUiMessages } from "../api/adapters";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));

// 🔒 PA-3 invariant under test: the clarify card's question/options come ONLY from the
// backend `clarify_options` frame (validated/clamped 2-4 server-side), never from LLM text.
const FRAME = {
  type: "clarify_options",
  question: "接下来往哪个方向推进?",
  options: [
    { label: "先出大纲", hint: "快速对齐结构" },
    { label: "直接生成整页 HTML", hint: "暗色磨砂玻璃风格" },
    { label: "再补充资料", hint: "" },
  ],
} as const;

describe("clarify_options frame (PA-3)", () => {
  it("appends an arslan message item carrying clarifyOptions and clears thinking", () => {
    const store = () => useArslanStore.getState();
    store().setThinking(true);
    store().handleFrame(FRAME as any);

    const st = store();
    expect(st.thinking).toBe(false); // clarify_options is a RESPONDING type
    const item = st.items[st.items.length - 1];
    expect(item.kind).toBe("message");
    expect(item.role).toBe("arslan");
    expect(item.content).toBe(FRAME.question);
    expect(item.clarifyOptions).toEqual({
      question: FRAME.question,
      options: FRAME.options,
      answered: false,
    });
  });

  it("markClarifyAnswered flips the card to answered exactly once (one-shot)", () => {
    const store = () => useArslanStore.getState();
    store().handleFrame(FRAME as any);
    const id = store().items[store().items.length - 1].id;

    store().markClarifyAnswered(id);
    const item = store().items[store().items.length - 1];
    expect(item.clarifyOptions?.answered).toBe(true);

    // idempotent: a second call changes nothing else
    store().markClarifyAnswered(id);
    expect(store().items[store().items.length - 1].clarifyOptions?.answered).toBe(true);
    // and a non-clarify item id is a no-op
    store().markClarifyAnswered(999999);
    expect(store().items.length).toBe(1);
  });

  it("toUiMessages passes clarifyOptions through to the UI Message", () => {
    const store = () => useArslanStore.getState();
    store().handleFrame(FRAME as any);

    const ui = toUiMessages(store().items);
    const msg = ui[ui.length - 1];
    expect(msg.sender).toBe("arslan");
    expect(msg.clarifyOptions?.question).toBe(FRAME.question);
    expect(msg.clarifyOptions?.options.map((o) => o.label)).toEqual([
      "先出大纲",
      "直接生成整页 HTML",
      "再补充资料",
    ]);
  });
});
