import { useCallback, useEffect, useRef, useState } from "react";
import { permissionModeApi, type ModeState, type PermissionMode } from "../../api/permissionMode";
import { useArslanStore } from "../../stores/arslanStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { asMode } from "./modes";

/**
 * S5a: one conversation's permission mode, for the pill and the strip above the composer. The server pushes nothing
 * when the mode or its fallback changes, so the window asks again: on a conversation switch, when a turn ends (a
 * sandbox that failed to start is only learnt then), when this window's settings change what the fallback reads,
 * and when the window comes back into view. No polling.
 */
export function usePermissionMode(conversationId: string) {
  const [state, setState] = useState<ModeState | null>(null);
  const [saveFailed, setSaveFailed] = useState(false);
  // Each stored change counts here, so the answer to a GET asked before it is dropped, not shown over it.
  const changes = useRef(0);
  const [asks, setAsks] = useState(0);
  const askAgain = useCallback(() => setAsks((n) => n + 1), []);
  const defaultMode = asMode(useSettingsStore((s) => s.settings?.default_permission_mode));
  const settingsKey = useSettingsStore((s) =>
    `${s.settings?.terminal_sandbox_enabled}|${s.settings?.workspace_dir}|${s.settings?.default_permission_mode}`);

  useEffect(() => { setState(null); setSaveFailed(false); }, [conversationId]);   // never the last conversation's

  useEffect(() => {
    let alive = true;
    const asked = changes.current;
    Promise.resolve().then(() => permissionModeApi.get(conversationId))
      .then((r) => { if (alive && changes.current === asked) setState(r); })
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

  const stored = (r: ModeState) => { changes.current += 1; setState(r); };

  const pick = useCallback(async (mode: PermissionMode) => {
    setSaveFailed(false);
    try {
      stored(await permissionModeApi.set(conversationId, mode));
    } catch {
      setSaveFailed(true);
    }
  }, [conversationId]);

  const start = useCallback(async () => {
    setSaveFailed(false);
    try {
      stored(await permissionModeApi.start(conversationId));
    } catch (e) {
      // 409: another window already pressed Start; show what the server has now.
      if ((e as { status?: number }).status === 409) askAgain(); else setSaveFailed(true);
    }
  }, [conversationId, askAgain]);

  return { state, defaultMode, saveFailed, pick, start };
}

export type PermissionModeControl = ReturnType<typeof usePermissionMode>;
