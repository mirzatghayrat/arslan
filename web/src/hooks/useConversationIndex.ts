import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ServerConversation } from "../lib/sessionPersistence";
import { metaFrom, type ConversationMeta } from "../lib/conversationMeta";

/** The server's conversation list, kept fresh while the window is visible: each conversation's
 *  kind and state for the sidebar's glyphs, and conversations started elsewhere (a task handed over
 *  from the iPhone) so they appear without a restart. Failures keep the last good list. */
export function useConversationIndex(intervalMs = 8000) {
  const [rows, setRows] = useState<ServerConversation[]>([]);
  const [meta, setMeta] = useState<Record<string, ConversationMeta>>({});
  const busy = useRef(false);
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (busy.current || (typeof document !== "undefined" && document.visibilityState === "hidden")) return;
      busy.current = true;
      try {
        const next = await api.listConversations();
        if (!cancelled && Array.isArray(next)) { setRows(next); setMeta(metaFrom(next)); }
      } catch { /* offline or booting: keep the last good list */ }
      finally { busy.current = false; }
    };
    void load();
    const timer = setInterval(load, intervalMs);
    const onVisible = () => { if (document.visibilityState === "visible") void load(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { cancelled = true; clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [intervalMs]);
  return { rows, meta };
}
