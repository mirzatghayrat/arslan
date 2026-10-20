/** K2b: facts are looked for after the turn, outside its lock, so they can arrive while the next
 *  turn runs. The line still goes under the reply it belongs to (the frame's reply_message_id,
 *  which the server sets: tests/server/test_after_turn_k2b.py checks it on the wire), and it never
 *  clears the next turn's thinking. */
import { describe, it, expect } from "vitest";

import { useArslanStore, initialArslanState } from "../stores/arslanStore";

const fact = (content: string, extra: Record<string, unknown> = {}) =>
  ({ type: "fact_saved", content, sensitive: false, entry_id: `e-${content.length}`, version: 1, ...extra }) as never;

function answer(messageId: number, text: string) {
  const store = useArslanStore.getState();
  store.handleFrame({ type: "stream_start", source: "arslan" } as never);
  store.handleFrame({ type: "stream_chunk", content: text } as never);
  store.handleFrame({ type: "stream_end", message_id: messageId } as never);   // exactly as the server sends it
}

function userSays(id: number, content: string) {
  const { items } = useArslanStore.getState();
  useArslanStore.setState({ items: [...items, { id, kind: "message", role: "user", content }] as never });
}

describe("a fact that arrives after its turn", () => {
  it("does not clear the thinking indicator of the turn that is running", () => {
    useArslanStore.setState({ ...initialArslanState(), thinking: true });
    useArslanStore.getState().handleFrame(fact("用户关注 Hermes", { reply_message_id: 1 }));
    expect(useArslanStore.getState().thinking).toBe(true);
  });

  it("sits under the reply of its own turn, even once the next message is sent", () => {
    useArslanStore.setState(initialArslanState());
    userSays(-1, "我在关注 Hermes");
    answer(1, "好的");
    userSays(-2, "那天气呢？");
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "arslan" } as never);
    useArslanStore.getState().handleFrame(fact("用户关注 Hermes", { reply_message_id: 1 }));
    useArslanStore.getState().handleFrame(fact("用户在做 Sluice", { reply_message_id: 1 }));
    const items = useArslanStore.getState().items;
    expect(items.map((i) => i.kind === "fact" ? "fact" : `${i.role}:${i.content}`)).toEqual(
      ["user:我在关注 Hermes", "arslan:好的", "fact", "user:那天气呢？"]);
    expect(items[2].facts?.map((f) => f.content)).toEqual(["用户关注 Hermes", "用户在做 Sluice"]);
  });

  it("starts its own line when the turn before already has one", () => {
    useArslanStore.setState(initialArslanState());
    answer(1, "one");
    useArslanStore.getState().handleFrame(fact("first fact", { reply_message_id: 1 }));
    userSays(-2, "next");
    answer(2, "two");
    useArslanStore.getState().handleFrame(fact("second fact", { reply_message_id: 2 }));
    const kinds = useArslanStore.getState().items.map((i) => i.kind === "fact" ? `fact:${i.content}` : i.content);
    expect(kinds).toEqual(["one", "fact:first fact", "next", "two", "fact:second fact"]);
  });
});
