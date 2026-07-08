import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { useArslanStore, initialArslanState, STALL_MS } from "./arslanStore";

/**
 * HX-4 / A1 — working indicators bound to runtime frames only + 90s stall watchdog.
 *
 * Invariants under test:
 *  - activity flags are SET only by runtime frames (stream_start/routing/tool_call…)
 *    and CLEARED by stream_end/error;
 *  - every incoming frame refreshes lastFrameAt and un-stalls;
 *  - checkStall() marks the turn `stalled` when active and no frame has arrived
 *    for > STALL_MS; it never stalls an idle store.
 */
describe("stall watchdog (HX-4 / A1)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-08T12:00:00Z"));
    useArslanStore.setState(initialArslanState(), true);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("stream_start sets activity + lastFrameAt; stream_end clears everything", () => {
    const s = useArslanStore.getState();
    s.handleFrame({ type: "stream_start", source: "arslan" } as never);
    let st = useArslanStore.getState();
    expect(st.streaming).toBe(true);
    expect(st.lastFrameAt).toBe(Date.now());
    expect(st.stalled).toBe(false);

    useArslanStore.getState().handleFrame({ type: "stream_chunk", content: "hi" } as never);
    useArslanStore.getState().handleFrame({ type: "stream_end", message_id: 1 } as never);
    st = useArslanStore.getState();
    expect(st.streaming).toBe(false);
    expect(st.stalled).toBe(false);
    // Well past the threshold after the turn ended: still not stalled (idle).
    vi.advanceTimersByTime(STALL_MS * 2);
    useArslanStore.getState().checkStall();
    expect(useArslanStore.getState().stalled).toBe(false);
  });

  it("tool_call refreshes lastFrameAt", () => {
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "spawn", spawn_id: 3 } as never);
    const t0 = useArslanStore.getState().lastFrameAt;
    vi.advanceTimersByTime(60_000);
    useArslanStore.getState().handleFrame({ type: "tool_call", tool: "web_search", args_summary: "q" } as never);
    const t1 = useArslanStore.getState().lastFrameAt;
    expect(t1).not.toBeNull();
    expect(t1! - t0!).toBe(60_000);
    // 60s later (120s after stream_start but only 60s after the tool_call): not stalled.
    vi.advanceTimersByTime(60_000);
    useArslanStore.getState().checkStall();
    expect(useArslanStore.getState().stalled).toBe(false);
  });

  it("no frames for >90s while active → stalled", () => {
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "arslan" } as never);
    vi.advanceTimersByTime(STALL_MS + 1_000);
    useArslanStore.getState().checkStall();
    expect(useArslanStore.getState().stalled).toBe(true);
    // Activity flags themselves are untouched — only the presentation flips.
    expect(useArslanStore.getState().streaming).toBe(true);
  });

  it("a late frame un-stalls", () => {
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "arslan" } as never);
    vi.advanceTimersByTime(STALL_MS + 1_000);
    useArslanStore.getState().checkStall();
    expect(useArslanStore.getState().stalled).toBe(true);

    useArslanStore.getState().handleFrame({ type: "tool_call", tool: "web_search", args_summary: "q" } as never);
    const st = useArslanStore.getState();
    expect(st.stalled).toBe(false);
    expect(st.lastFrameAt).toBe(Date.now());
  });

  it("thinking (user send, no frame yet) also arms the watchdog", () => {
    useArslanStore.getState().setThinking(true);
    expect(useArslanStore.getState().lastFrameAt).toBe(Date.now());
    vi.advanceTimersByTime(STALL_MS + 1_000);
    useArslanStore.getState().checkStall();
    expect(useArslanStore.getState().stalled).toBe(true);
  });

  it("error frame ends the turn: cleared, not stalled", () => {
    useArslanStore.getState().handleFrame({ type: "stream_start", source: "arslan" } as never);
    useArslanStore.getState().handleFrame({ type: "error", message: "boom" } as never);
    vi.advanceTimersByTime(STALL_MS * 2);
    useArslanStore.getState().checkStall();
    const st = useArslanStore.getState();
    expect(st.streaming).toBe(false);
    expect(st.stalled).toBe(false);
  });

  it("checkStall never stalls an idle store even with a stale lastFrameAt", () => {
    useArslanStore.setState({ lastFrameAt: Date.now() - STALL_MS * 3 });
    useArslanStore.getState().checkStall();
    expect(useArslanStore.getState().stalled).toBe(false);
  });
});
