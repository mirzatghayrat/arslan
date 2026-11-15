import { useCallback, useRef, useState } from "react";
import { useWebSocket } from "./useWebSocket";

export interface SideLine { id: number; role: "user" | "arslan"; text: string; cancelled?: boolean }

type Frame = { type?: string; messages?: { message_id: number; role: string; content: string }[];
  message_id?: number | null; role?: string; content?: string };

let clientSeq = -1;

/**
 * SIDE-2: a side chat is a conversation of its own, so its tab talks to it over its own socket, as the main chat does
 * for its conversation (`/ws/arslan/{id}`, `user_message`). Only what a read-only side chat shows is kept: its messages
 * and the reply being streamed. Nothing is sent but what `send` is given.
 */
export function useSideChat(id: string) {
  const [lines, setLines] = useState<SideLine[]>([]);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const live = useRef<string | null>(null);

  const onFrame = useCallback((raw: unknown) => {
    const f = raw as Frame;
    const end = (text: string | null, messageId: number | null | undefined, cancelled = false) => {
      live.current = null;
      setStreaming(null);
      setBusy(false);
      if (text) setLines((prev) => (messageId != null && prev.some((l) => l.id === messageId) ? prev
        : [...prev, { id: messageId ?? clientSeq--, role: "arslan", text, ...(cancelled ? { cancelled } : {}) }]));
    };
    switch (f.type) {
      case "history":
        live.current = null;
        setStreaming(null);
        setBusy(false);
        setLines((f.messages ?? []).filter((m) => m.role === "user" || m.role === "arslan")
          .map((m) => ({ id: m.message_id, role: m.role as SideLine["role"], text: m.content })));
        break;
      case "message":
        if ((f.role === "user" || f.role === "arslan") && f.content && f.message_id != null)
          setLines((prev) => [...prev, { id: f.message_id!, role: f.role as SideLine["role"], text: f.content! }]);
        break;
      case "run_in_progress":
        setBusy(true);
        break;
      case "stream_start":
        live.current = "";
        setStreaming("");
        setBusy(true);
        break;
      case "stream_chunk":
        if (live.current == null) break;
        live.current += f.content ?? "";
        setStreaming(live.current);
        break;
      case "stream_end":
        end(live.current, f.message_id);
        break;
      case "run_cancelled":
        end(live.current || null, f.message_id, true);
        break;
      case "error":
        end(live.current, null);
        break;
    }
  }, []);

  const { send: wsSend } = useWebSocket(`/ws/arslan/${id}`, onFrame);
  const send = useCallback((content: string) => {
    if (!content.trim()) return;
    setLines((prev) => [...prev, { id: clientSeq--, role: "user", text: content }]);
    setBusy(true);
    wsSend({ type: "user_message", content });
  }, [wsSend]);

  return { lines, streaming, busy, send };
}
