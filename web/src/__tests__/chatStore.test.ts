import { beforeEach, describe, expect, it } from "vitest";
import { useChatStore } from "../stores/chatStore";

describe("chatStore", () => {
  beforeEach(() => {
    useChatStore.setState({ messages: [], streaming: false, streamingText: "" });
  });

  it("appends a user message", () => {
    useChatStore.getState().addMessage({ id: 1, role: "user", content: "hi" });
    expect(useChatStore.getState().messages).toHaveLength(1);
  });

  it("accumulates streaming chunks then finalizes", () => {
    const s = useChatStore.getState();
    s.startStreaming();
    s.appendChunk("Hello");
    s.appendChunk(" world");
    expect(useChatStore.getState().streamingText).toBe("Hello world");
    s.finalizeStreaming(42);
    const state = useChatStore.getState();
    expect(state.streaming).toBe(false);
    expect(state.streamingText).toBe("");
    const last = state.messages[state.messages.length - 1];
    expect(last).toEqual({ id: 42, role: "assistant", content: "Hello world" });
  });

  it("replaces history wholesale", () => {
    useChatStore.getState().setHistory([
      { id: 1, role: "user", content: "a" },
      { id: 2, role: "assistant", content: "b" },
    ]);
    expect(useChatStore.getState().messages).toHaveLength(2);
  });
});
