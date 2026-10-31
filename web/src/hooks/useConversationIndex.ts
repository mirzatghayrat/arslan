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
  // INB4/INB5: the conversation the window shows is seen. The server marks its newest message each time it opens, whatever it
  // reads (a stopped job or a failed turn stops waiting on you too, #590 review F1), when the window shows again, and when it starts
  // reading "done, not seen" or "waiting" while open. A clean reply then reads idle (a chat) or done (a job) at once, without
  // waiting for the next poll. Only conversations the server lists are marked (a new one has nothing to mark yet), a live card
  // is marked once rather than on every poll, and a mark that failed is tried again after the next poll (#589 F3).
  const known = openId !== null && openId in meta;
  const openState = openId ? meta[openId]?.state : undefined;
  const marked = useRef<{ id: string; state: string | undefined } | null>(null);
  useEffect(() => {
    if (!openId || !visible) { marked.current = null; return; }
    if (!known) return;
    const prior = marked.current;
    marked.current = { id: openId, state: openState };       // what it reads now, marked or not, so the next reply or card marks again
    if (prior?.id === openId && (prior.state === openState || !ATTENTION.has(openState ?? ""))) return;
    api.markConversationSeen(openId).then(() => setMeta((all) => all[openId]?.state !== "done_unseen" ? all
      : { ...all, [openId]: { ...all[openId], state: all[openId].kind === "task" ? "done" : "idle" } }),
    () => { marked.current = null; /* tried again after the next poll */ });
  }, [openId, known, openState, visible, polls]);
  return { rows, meta };
}

/** States that ask for a fresh mark while the conversation stays open. */
const ATTENTION = new Set(["done_unseen", "waiting"]);
