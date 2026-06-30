import { useEffect, useRef, useState } from "react";
import { ReconnectingSocket, type SocketHandlers } from "../api/ws";

interface UseWebSocketResult {
  send: (obj: unknown) => void;
  reconnecting: boolean;
  setLastMessageId: (id: number) => void;
}

/**
 * Mount a ReconnectingSocket for the lifetime of the component.
 * `onMessage` is kept in a ref so re-renders don't reconnect.
 */
export function useWebSocket(
  path: string,
  onMessage: (msg: unknown) => void,
  opts: { onAuthFail?: () => void; enabled?: boolean; onOpen?: (path: string) => void } = {},
): UseWebSocketResult {
  const [reconnecting, setReconnecting] = useState(false);
  const socketRef = useRef<ReconnectingSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  // Keep onOpen in a ref so changing it doesn't tear down/reconnect the socket.
  const onOpenRef = useRef(opts.onOpen);
  onOpenRef.current = opts.onOpen;

  useEffect(() => {
    if (opts.enabled === false) return;
    const handlers: SocketHandlers = {
      onMessage: (m) => onMessageRef.current(m),
      onReconnecting: () => setReconnecting(true),
      onOpen: () => {
        setReconnecting(false);
        onOpenRef.current?.(path);
      },
      onAuthFail: opts.onAuthFail,
    };
    const socket = new ReconnectingSocket(path, handlers);
    socketRef.current = socket;
    socket.connect();
    return () => socket.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, opts.enabled]);

  return {
    send: (obj) => socketRef.current?.send(obj),
    reconnecting,
    setLastMessageId: (id) => {
      if (socketRef.current) socketRef.current.lastMessageId = id;
    },
  };
}
