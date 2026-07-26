/**
 * The send() silent drop (v0.1.0 field bug): a message sent while the socket
 * was CONNECTING — the packaged app's normal state for the first seconds of
 * its life — was optimistically rendered by the caller and silently discarded
 * here. The user saw their bubble, the server saw nothing, and navigating
 * away destroyed the only copy. Zero errors anywhere.
 *
 * Contract now: send() while not-OPEN QUEUES; the queue FLUSHES in order on
 * open; a genuinely-open socket still sends immediately.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ReconnectingSocket } from "../api/ws";

class FakeWS {
  static instances: FakeWS[] = [];
  static OPEN = 1; static CONNECTING = 0;
  readyState = 0; // CONNECTING
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: unknown) => void) | null = null;
  onclose: ((e: unknown) => void) | null = null;
  url: string;
  constructor(url: string) { this.url = url; FakeWS.instances.push(this); }
  send(d: string) {
    if (this.readyState !== 1) throw new Error("InvalidStateError");
    this.sent.push(d);
  }
  close() { this.readyState = 3; }
  open() { this.readyState = 1; this.onopen?.(); }
}

beforeEach(() => {
  FakeWS.instances = [];
  vi.stubGlobal("WebSocket", FakeWS as unknown as typeof WebSocket);
  vi.stubGlobal("location", { protocol: "http:", host: "127.0.0.1:8791" });
});
afterEach(() => vi.unstubAllGlobals());

describe("ReconnectingSocket outbox", () => {
  it("queues while CONNECTING and flushes in order on open", () => {
    const c = new ReconnectingSocket("/ws/arslan/t1", { onMessage: () => {} });
    c.connect();
    const ws = FakeWS.instances[0];
    expect(ws.readyState).toBe(0);

    c.send({ type: "user_message", content: "first" });
    c.send({ type: "user_message", content: "second" });
    // Not silently dropped:
    expect(ws.sent).toHaveLength(0);

    ws.open();
    expect(ws.sent.map((s) => JSON.parse(s).content)).toEqual(["first", "second"]);
  });

  it("still sends immediately when already open (control)", () => {
    const c = new ReconnectingSocket("/ws/arslan/t1", { onMessage: () => {} });
    c.connect();
    FakeWS.instances[0].open();
    c.send({ type: "user_message", content: "direct" });
    expect(FakeWS.instances[0].sent).toHaveLength(1);
  });
});
