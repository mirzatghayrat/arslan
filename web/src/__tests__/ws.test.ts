import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReconnectingSocket, backoffDelay } from "../api/ws";

// Minimal fake WebSocket capturing instances for assertions.
class FakeWS {
  static instances: FakeWS[] = [];
  static OPEN = 1;
  url: string;
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  sent: string[] = [];
  constructor(url: string) {
    this.url = url;
    FakeWS.instances.push(this);
  }
  send(d: string) {
    this.sent.push(d);
  }
  close() {
    this.readyState = 3;
    this.onclose?.({ code: 1000 });
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  emit(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) });
  }
  fail(code: number) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

beforeEach(() => {
  FakeWS.instances = [];
  vi.stubGlobal("WebSocket", FakeWS as unknown as typeof WebSocket);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("backoffDelay", () => {
  it("grows exponentially and caps at 30s", () => {
    expect(backoffDelay(0)).toBeLessThanOrEqual(1200);
    expect(backoffDelay(3)).toBeGreaterThan(4000);
    expect(backoffDelay(10)).toBeLessThanOrEqual(30000 * 1.2);
  });
});

describe("ReconnectingSocket", () => {
  it("delivers parsed messages to the handler", () => {
    const received: unknown[] = [];
    const s = new ReconnectingSocket("/ws/chat/1", { onMessage: (m) => received.push(m) });
    s.connect();
    FakeWS.instances[0].open();
    FakeWS.instances[0].emit({ type: "stream_chunk", content: "hi" });
    expect(received).toEqual([{ type: "stream_chunk", content: "hi" }]);
  });

  it("auto-reconnects on abnormal close (4408)", () => {
    const s = new ReconnectingSocket("/ws/chat/1", { onMessage: () => {} });
    s.connect();
    FakeWS.instances[0].open();
    FakeWS.instances[0].fail(4408);
    vi.advanceTimersByTime(2000);
    expect(FakeWS.instances.length).toBe(2); // reconnected
  });

  it("does NOT reconnect on 4001 auth failure", () => {
    const onAuthFail = vi.fn();
    const s = new ReconnectingSocket("/ws/chat/1", { onMessage: () => {}, onAuthFail });
    s.connect();
    FakeWS.instances[0].open();
    FakeWS.instances[0].fail(4001);
    vi.advanceTimersByTime(5000);
    expect(FakeWS.instances.length).toBe(1); // no reconnect
    expect(onAuthFail).toHaveBeenCalled();
  });

  it("replies pong to a server ping", () => {
    const s = new ReconnectingSocket("/ws/chat/1", { onMessage: () => {} });
    s.connect();
    FakeWS.instances[0].open();
    FakeWS.instances[0].emit({ type: "ping", ts: 123 });
    expect(FakeWS.instances[0].sent).toContain(JSON.stringify({ type: "pong", ts: 123 }));
  });

  it("does not reconnect after an intentional close", () => {
    const s = new ReconnectingSocket("/ws/chat/1", { onMessage: () => {} });
    s.connect();
    FakeWS.instances[0].open();
    s.close();
    vi.advanceTimersByTime(5000);
    expect(FakeWS.instances.length).toBe(1);
  });

  it("sends a resume frame with last_message_id on reconnect", () => {
    const s = new ReconnectingSocket("/ws/chat/1", { onMessage: () => {} });
    s.lastMessageId = 5;
    s.connect();
    FakeWS.instances[0].open();
    FakeWS.instances[0].fail(4408);
    vi.advanceTimersByTime(2000);
    // The new socket must announce where to resume from.
    FakeWS.instances[1].open();
    expect(FakeWS.instances[1].sent).toContain(
      JSON.stringify({ type: "resume", last_message_id: 5 }),
    );
  });

  it("does NOT reconnect on clean close 1000 or not-found 4004", () => {
    const s1 = new ReconnectingSocket("/ws/chat/1", { onMessage: () => {} });
    s1.connect();
    FakeWS.instances[0].open();
    FakeWS.instances[0].fail(1000);
    vi.advanceTimersByTime(5000);
    expect(FakeWS.instances.length).toBe(1);

    FakeWS.instances = [];
    const s2 = new ReconnectingSocket("/ws/chat/2", { onMessage: () => {} });
    s2.connect();
    FakeWS.instances[0].open();
    FakeWS.instances[0].fail(4004);
    vi.advanceTimersByTime(5000);
    expect(FakeWS.instances.length).toBe(1);
  });

  it("fires onReconnecting only from the second attempt", () => {
    const onReconnecting = vi.fn();
    const s = new ReconnectingSocket("/ws/chat/1", { onMessage: () => {}, onReconnecting });
    s.connect();
    FakeWS.instances[0].open();
    FakeWS.instances[0].fail(4408);          // attempt 1 -> no banner
    vi.advanceTimersByTime(2000);
    expect(onReconnecting).not.toHaveBeenCalled();
    FakeWS.instances[1].fail(4408);          // attempt 2 -> banner
    vi.advanceTimersByTime(5000);
    expect(onReconnecting).toHaveBeenCalled();
  });
});
