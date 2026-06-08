import { useAuthStore } from "../stores/authStore";

const NO_RECONNECT_CODES = new Set([1000, 4001, 4004]);

/** Exponential backoff with ±20% jitter, capped at 30s. Deterministic mid-range. */
export function backoffDelay(attempt: number): number {
  const base = Math.min(1000 * 2 ** attempt, 30000);
  const jitter = base * 0.2 * (Math.random() * 2 - 1);
  return Math.max(0, base + jitter);
}

export interface SocketHandlers {
  onMessage: (msg: unknown) => void;
  onOpen?: () => void;
  onReconnecting?: (attempt: number) => void;
  onAuthFail?: () => void;
  onClosed?: (code: number) => void;
}

/**
 * WebSocket wrapper with: token query param, app-level pong replies,
 * exponential-backoff reconnection, and a resume hook (lastMessageId).
 */
export class ReconnectingSocket {
  private path: string;
  private handlers: SocketHandlers;
  private ws: WebSocket | null = null;
  private attempt = 0;
  private intentionalClose = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  lastMessageId = 0;

  constructor(path: string, handlers: SocketHandlers) {
    this.path = path;
    this.handlers = handlers;
  }

  private url(): string {
    const token = useAuthStore.getState().token;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const q = token ? `?token=${encodeURIComponent(token)}` : "";
    return `${proto}://${location.host}${this.path}${q}`;
  }

  connect(): void {
    this.intentionalClose = false;
    // Detach any previous socket's handlers so its late onclose can't trigger a ghost reconnect.
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onclose = null;
    }
    const ws = new WebSocket(this.url());
    this.ws = ws;

    ws.onopen = () => {
      this.attempt = 0;
      this.handlers.onOpen?.();
      if (this.lastMessageId > 0) {
        this.send({ type: "resume", last_message_id: this.lastMessageId });
      }
    };

    ws.onmessage = (event: MessageEvent) => {
      let msg: unknown;
      try {
        msg = JSON.parse(event.data as string);
      } catch {
        return;
      }
      const m = msg as { type?: string; ts?: number };
      if (m.type === "ping") {
        this.send({ type: "pong", ts: m.ts });
        return;
      }
      this.handlers.onMessage(msg);
    };

    ws.onclose = (event: CloseEvent) => {
      this.handlers.onClosed?.(event.code);
      if (event.code === 4001) {
        this.handlers.onAuthFail?.();
        return;
      }
      if (this.intentionalClose || NO_RECONNECT_CODES.has(event.code)) return;
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    const delay = backoffDelay(this.attempt);
    this.attempt += 1;
    if (this.attempt >= 2) this.handlers.onReconnecting?.(this.attempt);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  send(obj: unknown): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
    }
  }

  close(): void {
    this.intentionalClose = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }
}
