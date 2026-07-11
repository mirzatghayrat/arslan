import { describe, it, expect, beforeEach } from "vitest";
import { useArslanStore, initialArslanState } from "./arslanStore";

/**
 * S3-M3 cost visibility — the stream_end frame's usage payload must land on the
 * created thread item so the bubble can render its usage chip. run_cancelled
 * items are finalized without usage (the turn never reached its terminal frame).
 */

const USAGE = { tokens_in: 100, tokens_out: 50, tokens_total: 150, estimated: false, usd: 0.0021 };

describe("stream_end usage lands on the created item (S3-M3)", () => {
  beforeEach(() => {
    useArslanStore.setState(initialArslanState(), true);
  });

  it("usage from the frame rides the finalized item", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "stream_start", source: "arslan" } as never);
    useArslanStore.getState().handleFrame({ type: "stream_chunk", content: "hello" } as never);
    useArslanStore.getState().handleFrame({ type: "stream_end", message_id: 7, usage: USAGE } as never);
    const items = useArslanStore.getState().items;
    expect(items).toHaveLength(1);
    expect(items[0].usage).toEqual(USAGE);
  });

  it("stream_end without usage → item has no usage field", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "stream_start", source: "arslan" } as never);
    useArslanStore.getState().handleFrame({ type: "stream_chunk", content: "hello" } as never);
    useArslanStore.getState().handleFrame({ type: "stream_end", message_id: 8 } as never);
    const items = useArslanStore.getState().items;
    expect(items[0].usage).toBeUndefined();
  });

  it("spawn-turn usage rides the spawn deliverable item", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "stream_start", source: "spawn", spawn_id: 3, run_id: 9 } as never);
    useArslanStore.getState().handleFrame({ type: "stream_chunk", content: "deliverable" } as never);
    useArslanStore.getState().handleFrame({ type: "stream_end", message_id: 9, usage: USAGE } as never);
    const items = useArslanStore.getState().items;
    expect(items[0].role).toBe("spawn");
    expect(items[0].usage).toEqual(USAGE);
  });

  it("run_cancelled items carry no usage", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "stream_start", source: "spawn", spawn_id: 3, run_id: 12 } as never);
    useArslanStore.getState().handleFrame({ type: "stream_chunk", content: "partial" } as never);
    useArslanStore.getState().handleFrame({ type: "run_cancelled", run_id: 12, message_id: 10 } as never);
    const items = useArslanStore.getState().items;
    expect(items).toHaveLength(1);
    expect(items[0].cancelled).toBe(true);
    expect(items[0].usage).toBeUndefined();
  });
});
