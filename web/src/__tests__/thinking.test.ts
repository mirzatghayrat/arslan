import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState({ thinking: false, streaming: false } as any));

it("setThinking(true) marks thinking", () => {
  (useArslanStore.getState() as any).setThinking(true);
  expect((useArslanStore.getState() as any).thinking).toBe(true);
});

it("the first response frame clears thinking", () => {
  (useArslanStore.getState() as any).setThinking(true);
  useArslanStore.getState().handleFrame({ type: "stream_start", source: "arslan" } as any);
  expect((useArslanStore.getState() as any).thinking).toBe(false);
});

it("routing frame also clears thinking", () => {
  (useArslanStore.getState() as any).setThinking(true);
  useArslanStore.getState().handleFrame({ type: "routing", spawn_id: 4, spawn_name: "x" } as any);
  expect((useArslanStore.getState() as any).thinking).toBe(false);
});

it("history/roster_update do NOT set thinking on their own", () => {
  useArslanStore.setState({ thinking: false } as any);
  useArslanStore.getState().handleFrame({ type: "roster_update", members: [] } as any);
  expect((useArslanStore.getState() as any).thinking).toBe(false);
});
