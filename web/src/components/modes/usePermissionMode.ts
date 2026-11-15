import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { permissionModeApi, type ModeState, type PermissionMode } from "../../api/permissionMode";
import { useArslanStore } from "../../stores/arslanStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { asMode, isSideChat } from "./modes";

/**
 * S5a: one conversation's permission mode, for the pill and the strip above the composer. The server pushes nothing
 * when the mode or its fallback changes, so the window asks again: on a conversation switch, when a turn ends (a
 * sandbox that failed to start is only learnt then), when this window's settings change what the fallback reads,
 * and when the window comes back into view. No polling.
 */
export function usePermissionMode(conversationId: string) {
  // Each answer is kept with the conversation it is for, so the first render after a switch already shows nothing of
  // the last one (no effect has to clear it first).
  const [held, setHeld] = useState<{ id: string; state: ModeState } | null>(null);
  const [failedFor, setFailedFor] = useState<string | null>(null);
  const state = held?.id === conversationId ? held.state : null;
  const saveFailed = failedFor === conversationId;
  // The conversation open now: a PUT or a POST that answers after a switch is dropped, not shown on the next one.
  const open = useRef(conversationId);
  useLayoutEffect(() => { open.current = conversationId; }, [conversationId]);
  // SIDE-1: a side chat runs in its parent's mode and never sets one (the server answers 422).
  const inherited = isSideChat(conversationId);
  // Each stored change counts here, so the answer to a GET asked before it is dropped, not shown over it.
  const changes = useRef(0);
  const [asks, setAsks] = useState(0);
  const askAgain = useCallback(() => setAsks((n) => n + 1), []);
  const defaultMode = asMode(useSettingsStore((s) => s.settings?.default_permission_mode));
  const settingsKey = useSettingsStore((s) =>
    `${s.settings?.terminal_sandbox_enabled}|${s.settings?.workspace_dir}|${s.settings?.default_permission_mode}`);

  useEffect(() => {
    let alive = true;
    const asked = changes.current;
    Promise.resolve().then(() => permissionModeApi.get(conversationId))
      .then((r) => { if (alive && changes.current === asked) setHeld({ id: conversationId, state: r }); })
      .catch(() => {});
    return () => { alive = false; };
  }, [conversationId, settingsKey, asks]);

  const streaming = useArslanStore((s) => s.streaming);
  const wasStreaming = useRef(streaming);
  useEffect(() => {
    if (wasStreaming.current && !streaming) askAgain();
    wasStreaming.current = streaming;
  }, [streaming, askAgain]);

  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === "visible") askAgain(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [askAgain]);

  /** A PUT's or a POST's answer for `id`; once another conversation is open it is dropped and drops no GET. */
  const stored = (id: string, r: ModeState) => {
    if (open.current !== id) return;
    changes.current += 1;
    setHeld({ id, state: r });
  };
  const failed = (id: string) => { if (open.current === id) setFailedFor(id); };

  const pick = useCallback(async (mode: PermissionMode) => {
    if (inherited) return;
    const id = conversationId;
    setFailedFor(null);
    try {
      stored(id, await permissionModeApi.set(id, mode));
    } catch {
      failed(id);
    }
  }, [conversationId, inherited]);

  const start = useCallback(async () => {
    if (inherited) return;
    const id = conversationId;
    setFailedFor(null);
    try {
      stored(id, await permissionModeApi.start(id));
    } catch (e) {
      // 409: another window already pressed Start; show what the server has now.
      if ((e as { status?: number }).status !== 409) failed(id);
      else if (open.current === id) askAgain();
    }
  }, [conversationId, inherited, askAgain]);

  return { state, defaultMode, saveFailed, inherited, pick, start };
}

export type PermissionModeControl = ReturnType<typeof usePermissionMode>;
