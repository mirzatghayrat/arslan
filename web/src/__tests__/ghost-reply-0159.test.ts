/**
 * 0.1.59: no ghost reply after a reconnect. Seen recording the promo on v0.1.59-beta.2: after a
 * complete answer, a frozen half copy of it and a "working" row whose timer never stopped; the
 * database held one message. A replay cut by a second socket drop left the live stream set, and
 * `history` did not clear it.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

const frame = (f: Record<string, unknown>) => useArslanStore.getState().handleFrame(f as never);
const state = () => useArslanStore.getState();
const ANSWER = "Here's your memo, turned into a to-do list for Pocket Garden: Ask the artist for the sketches.";
const history = (withAnswer: boolean) => frame({ type: "history", messages: [
  { message_id: 14, role: "user", content: "Transcribe the voice memo", spawn_id: null },
  ...(withAnswer ? [{ message_id: 15, role: "arslan", content: ANSWER, spawn_id: null, run_id: 14 }] : []),
] });
const messages = () => state().items.filter((it) => it.kind === "message");

beforeEach(() => useArslanStore.setState(initialArslanState(), true));

describe("a reconnect never leaves a ghost reply", () => {
  it("the reported sequence: a replay cut short, then history — one answer, no stream, no timer", () => {
    history(true);
    // Socket 2 re-attached while the run was still finishing: run_in_progress + a replay…
    frame({ type: "run_in_progress", run_id: 14 });
    frame({ type: "stream_start", source: "arslan", run_id: 14 });
    frame({ type: "stream_chunk", content: "Here's your memo, turned into a to-do list for Pocket Garden: " });
    frame({ type: "stream_chunk", content: "Ask the artist for the" });
    // …cut by a third drop. Socket 3: history only (the run has finished meanwhile).
    history(true);
    expect(messages().map((m) => m.id)).toEqual([14, 15]);
    expect(state().streaming).toBe(false);
    expect(state().streamingText).toBe("");
    expect(state().thinking).toBe(false);
    expect(state().workStartedAt).toBeNull();
  });

  it("a replayed stream_end for an answer already shown adds no second copy", () => {
    history(true);
    frame({ type: "stream_start", source: "arslan", run_id: 14 });
    frame({ type: "stream_chunk", content: ANSWER });
    frame({ type: "stream_end", message_id: 15, run_id: 14 });
    expect(messages().map((m) => m.id)).toEqual([14, 15]);
    expect(state().streaming).toBe(false);
  });

  it("a run still in flight is rebuilt by the replay after history and finishes once", () => {
    frame({ type: "stream_start", source: "arslan", run_id: 14 });
    frame({ type: "stream_chunk", content: "Here's your" });
    history(false);                       // the socket dropped mid-answer; the answer is not saved yet
    frame({ type: "run_in_progress", run_id: 14 });
    frame({ type: "stream_start", source: "arslan", run_id: 14 });
    frame({ type: "stream_chunk", content: ANSWER });
    expect(state().streamingText).toBe(ANSWER);  // rebuilt from the replay, not doubled
    frame({ type: "stream_end", message_id: 15, run_id: 14 });
    expect(messages().map((m) => [m.id, m.content])).toEqual([[14, "Transcribe the voice memo"], [15, ANSWER]]);
  });
});
