import { describe, it, expect, vi, beforeEach } from "vitest";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { api } from "../api/client";

/**
 * S3-M1 — cancellable runs, frontend wiring.
 *
 * Invariants under test:
 *  - stream_start carries the recorded run's id (spawn runs only) → activeRunId;
 *  - stream_end / error / run_cancelled all clear activeRunId (no stale cancel target);
 *  - run_cancelled finalizes the live bubble: partial text becomes a cancelled item
 *    (the server persisted the canonical copy — this is the live-session echo);
 *  - run_cancelled with NO partial text appends nothing (no ghost bubbles);
 *  - api.cancelRun POSTs /runs/{id}/cancel.
 */
describe("run cancel wiring (S3-M1)", () => {
  beforeEach(() => {
    useArslanStore.setState(initialArslanState(), true);
  });

  it("captures activeRunId from stream_start and clears it on stream_end", () => {
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 1, run_id: 42 } as never);
    expect(useArslanStore.getState().activeRunId).toBe(42);
    useArslanStore.getState().handleFrame({ type: "stream_chunk", content: "hi" } as never);
    useArslanStore.getState().handleFrame({ type: "stream_end", message_id: 1 } as never);
    expect(useArslanStore.getState().activeRunId).toBeNull();
  });

  it("stream_start without run_id (unrecorded stream) leaves activeRunId null", () => {
    useArslanStore.setState({ activeRunId: 7 });
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "arslan" } as never);
    expect(useArslanStore.getState().activeRunId).toBeNull();
  });

  it("run_cancelled finalizes the streaming bubble with the cancelled marker", () => {
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 1, run_id: 43 } as never);
    useArslanStore.getState().handleFrame({ type: "stream_chunk", content: "partial " } as never);
    useArslanStore.getState().handleFrame({ type: "run_cancelled", run_id: 43 } as never);
    const st = useArslanStore.getState();
    expect(st.streaming).toBe(false);
    expect(st.streamingText).toBe("");
    expect(st.activeRunId).toBeNull();
    expect(st.thinking).toBe(false);
    const last = st.items[st.items.length - 1];
    expect(last.content).toContain("partial ");
    expect(last.cancelled).toBe(true);
    expect(last.role).toBe("spawn");
    expect(last.spawnId).toBe(1);
  });

  it("run_cancelled with message_id uses it as the item id (server persisted copy)", () => {
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 2, run_id: 44 } as never);
    useArslanStore.getState().handleFrame({ type: "stream_chunk", content: "cut short" } as never);
    useArslanStore.getState().handleFrame({ type: "run_cancelled", run_id: 44, message_id: 99 } as never);
    const st = useArslanStore.getState();
    const last = st.items[st.items.length - 1];
    expect(last.id).toBe(99);
    expect(st.lastMessageId).toBe(99);
  });

  it("run_cancelled with no partial text appends NO item (server copy is canonical)", () => {
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 1, run_id: 45 } as never);
    useArslanStore.getState().handleFrame({ type: "run_cancelled", run_id: 45 } as never);
    const st = useArslanStore.getState();
    expect(st.items).toHaveLength(0);
    expect(st.streaming).toBe(false);
    expect(st.activeRunId).toBeNull();
  });

  it("error frame clears activeRunId", () => {
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 1, run_id: 46 } as never);
    useArslanStore.getState().handleFrame({ type: "error", message: "boom" } as never);
    expect(useArslanStore.getState().activeRunId).toBeNull();
  });

  it("history rebuild resets activeRunId", () => {
    useArslanStore.setState({ activeRunId: 5 });
    useArslanStore.getState().handleFrame({ type: "history", messages: [] } as never);
    expect(useArslanStore.getState().activeRunId).toBeNull();
  });

  it("history rebuild restores runId from the row's run_id (S3-M2)", () => {
    useArslanStore.getState().handleFrame({
      type: "history",
      messages: [
        { message_id: 1, role: "user", content: "analyze", spawn_id: null, run_id: null },
        { message_id: 2, role: "spawn_summary", content: "result", spawn_id: 7, run_id: 555 },
      ],
    } as never);
    const st = useArslanStore.getState();
    expect(st.items).toHaveLength(2);
    // Linked row: RunReplay entry point survives the reload.
    expect(st.items[1].runId).toBe(555);
    // Unlinked row: null run_id degrades to undefined (no replay entry).
    expect(st.items[0].runId).toBeUndefined();
  });
});

describe("run_in_progress reattach (S3-M2)", () => {
  beforeEach(() => {
    useArslanStore.setState(initialArslanState(), true);
  });

  it("run_in_progress arms the stop button: thinking=true + activeRunId, NO item created", () => {
    useArslanStore.getState().handleFrame({ type: "run_in_progress", run_id: 88 } as never);
    const st = useArslanStore.getState();
    expect(st.thinking).toBe(true);
    expect(st.activeRunId).toBe(88);
    // No item creation — the replayed stream frames rebuild state via existing paths.
    expect(st.items).toHaveLength(0);
    expect(st.streaming).toBe(false);
  });

  it("replayed stream frames after run_in_progress flow via the existing cases", () => {
    useArslanStore.getState().handleFrame({ type: "run_in_progress", run_id: 89 } as never);
    // Journal replay: stream_start (same run) then chunks, then live stream_end.
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 3, run_id: 89 } as never);
    expect(useArslanStore.getState().activeRunId).toBe(89);
    expect(useArslanStore.getState().streaming).toBe(true);
    useArslanStore.getState().handleFrame({ type: "stream_chunk", content: "resumed " } as never);
    const mid = useArslanStore.getState();
    expect(mid.thinking).toBe(false); // first real content clears thinking
    expect(mid.streamingText).toBe("resumed ");
    useArslanStore.getState().handleFrame({ type: "stream_end", message_id: 5 } as never);
    const st = useArslanStore.getState();
    expect(st.streaming).toBe(false);
    expect(st.activeRunId).toBeNull();
    expect(st.items[st.items.length - 1].content).toBe("resumed ");
  });

  it("server ordering (history THEN run_in_progress): rebuild clears, reattach re-arms", () => {
    // history rebuild still clears activeRunId...
    useArslanStore.setState({ activeRunId: 5, thinking: false });
    useArslanStore.getState().handleFrame({ type: "history", messages: [] } as never);
    expect(useArslanStore.getState().activeRunId).toBeNull();
    // ...and the run_in_progress that follows it (server sends it after history) re-arms.
    useArslanStore.getState().handleFrame({ type: "run_in_progress", run_id: 90 } as never);
    expect(useArslanStore.getState().activeRunId).toBe(90);
    expect(useArslanStore.getState().thinking).toBe(true);
  });
});

describe("api.cancelRun (S3-M1)", () => {
  beforeEach(() => {
    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 202,
      json: async () => ({ ok: true }),
    })) as never;
  });

  it("POSTs /runs/{id}/cancel", async () => {
    const result = await api.cancelRun(42);
    const [url, opts] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/runs/42/cancel");
    expect(opts.method).toBe("POST");
    expect(result).toEqual({ ok: true });
  });
});
