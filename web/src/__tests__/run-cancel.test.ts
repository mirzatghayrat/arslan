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
