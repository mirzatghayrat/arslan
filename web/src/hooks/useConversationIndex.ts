import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ServerConversation } from "../lib/sessionPersistence";
import { metaFrom, type ConversationMeta } from "../lib/conversationMeta";

/** The server's conversation list, kept fresh while the window is visible: each conversation's
 *  kind and state for the sidebar's glyphs, and conversations started elsewhere (a task handed over
 *  from the iPhone) so they appear without a restart. Failures keep the last good list. */
export function useConversationIndex(intervalMs = 8000, section: string | null = null, threadId: string | null = null) {
  // INB4: the open conversation is on screen only while the chat section shows it.
  const openId = section === "arslan" ? threadId : null;
  const [rows, setRows] = useState<ServerConversation[]>([]);
  const [meta, setMeta] = useState<Record<string, ConversationMeta>>({});
  const [visible, setVisible] = useState(() => typeof document === "undefined" || document.visibilityState !== "hidden");
  const [polls, setPolls] = useState(0);
  const busy = useRef(false);
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (busy.current || (typeof document !== "undefined" && document.visibilityState === "hidden")) return;
      busy.current = true;
      try {
        const next = await api.listConversations();
        if (!cancelled && Array.isArray(next)) { setRows(next); setMeta(metaFrom(next)); setPolls((n) => n + 1); }
      } catch { /* offline or booting: keep the last good list */ }
      finally { busy.current = false; }
    };
    void load();
    const timer = setInterval(load, intervalMs);
    const onVisible = () => { setVisible(document.visibilityState !== "hidden"); if (document.visibilityState === "visible") void load(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { cancelled = true; clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [intervalMs]);
  // INB4: the conversation the window shows is seen: once its reply or its job is done and the window is visible, the server marks
  // its newest message, and it reads idle (a chat) or done (a job) at once, without waiting for the next poll. A mark that failed
  // is tried again after the next poll while the server still says done_unseen (#589 F3).
  const openState = openId ? meta[openId]?.state : undefined;
  useEffect(() => {
    if (!openId || openState !== "done_unseen" || !visible) return;
    api.markConversationSeen(openId).then(() => setMeta((all) => all[openId]?.state !== "done_unseen" ? all
      : { ...all, [openId]: { ...all[openId], state: all[openId].kind === "task" ? "done" : "idle" } }), () => { /* the next poll shows it again */ });
  }, [openId, openState, visible, polls]);
  return { rows, meta };
}
