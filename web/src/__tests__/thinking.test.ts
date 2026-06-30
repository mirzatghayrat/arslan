import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState({ thinking: false, streaming: false, streamingText: "" } as any));

it("setThinking(true) marks thinking", () => {
  (useArslanStore.getState() as any).setThinking(true);
  expect((useArslanStore.getState() as any).thinking).toBe(true);
});

// stream_start should NOT clear thinking — it starts streaming but no content yet
it("stream_start does NOT clear thinking (thinking persists until first chunk)", () => {
  (useArslanStore.getState() as any).setThinking(true);
  useArslanStore.getState().handleFrame({ type: "stream_start", source: "arslan" } as any);
  const s = useArslanStore.getState() as any;
  expect(s.thinking).toBe(true);   // still thinking — no content yet
  expect(s.streaming).toBe(true);  // streaming has started
  expect(s.streamingText).toBe(""); // no content yet
});

// stream_chunk clears thinking (first real content arrived)
it("stream_chunk clears thinking and accumulates text", () => {
  (useArslanStore.getState() as any).setThinking(true);
  useArslanStore.getState().handleFrame({ type: "stream_start", source: "arslan" } as any);
  useArslanStore.getState().handleFrame({ type: "stream_chunk", content: "Hello" } as any);
  const s = useArslanStore.getState() as any;
  expect(s.thinking).toBe(false);
  expect(s.streamingText).toBe("Hello");
});

// routing frame does NOT clear thinking — it is an intermediate dispatch frame
// during the Arslan→spawn handoff. Thinking should persist through routing and
// only clear on stream_chunk (first real token) to avoid a dead-air gap.
it("routing frame does NOT clear thinking (thinking persists through dispatch)", () => {
  (useArslanStore.getState() as any).setThinking(true);
  useArslanStore.getState().handleFrame({ type: "routing", spawn_id: 4, spawn_name: "x" } as any);
  expect((useArslanStore.getState() as any).thinking).toBe(true);
});

// stream_end clears thinking (safety: no chunk ever arrived)
it("stream_end clears thinking even if no chunk arrived", () => {
  (useArslanStore.getState() as any).setThinking(true);
  useArslanStore.getState().handleFrame({ type: "stream_start", source: "arslan" } as any);
  // Force streaming=true so stream_end doesn't bail early
  useArslanStore.setState({ streaming: true } as any);
  useArslanStore.getState().handleFrame({ type: "stream_end", message_id: null } as any);
  expect((useArslanStore.getState() as any).thinking).toBe(false);
});

// error frame clears thinking
it("error frame clears thinking", () => {
  (useArslanStore.getState() as any).setThinking(true);
  useArslanStore.getState().handleFrame({ type: "error", message: "oops" } as any);
  expect((useArslanStore.getState() as any).thinking).toBe(false);
});

it("history/roster_update do NOT set thinking on their own", () => {
  useArslanStore.setState({ thinking: false } as any);
  useArslanStore.getState().handleFrame({ type: "roster_update", members: [] } as any);
  expect((useArslanStore.getState() as any).thinking).toBe(false);
});
