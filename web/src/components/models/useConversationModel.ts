import { useCallback, useEffect, useState } from "react";
import { fetchProviderModels } from "../../api/client";
import { conversationModelApi } from "../../api/conversationModel";
import type { ContextParts, ModelInfo, ProviderConfig } from "../../api/client.types";
import { useArslanStore } from "../../stores/arslanStore";
import type { ModelChoice } from "./ModelPicker";

/** Sent with the conversation id and its new choice when its model changes, so every place showing it
 *  follows without another request (WB1-2: the chip under the composer and the one in Overview). */
export const MODEL_CHANGED_EVENT = "arslan:conversation-model-changed";

/** One catalog fetch per provider per window, shared by every chip (for the ring's context size). */
const catalogs = new Map<number, Promise<ModelInfo[]>>();
function catalog(id: number): Promise<ModelInfo[]> {
  let p = catalogs.get(id);
  if (!p) { p = Promise.resolve().then(() => fetchProviderModels(id)).then((r) => r.models).catch(() => []); catalogs.set(id, p); }
  return p;
}
export function _resetChipCatalogs() { catalogs.clear(); }

/**
 * Which model THIS conversation runs on and how full its context is (0.1.58 §6, K4b), shared by the
 * model chip and the workbench's Overview (WB1-2): the conversation's own choice, else the primary
 * config; the last reply's provider-reported input and its estimated parts; the model's window.
 */
export function useConversationModel(conversationId: string, configs: ProviderConfig[]) {
  const [choice, setChoiceState] = useState<ModelChoice | null>(null);
  const [window_, setWindow] = useState<number | null>(null);
  const lastInput = useArslanStore((s) => {
    for (let i = s.items.length - 1; i >= 0; i--) { const u = s.items[i].usage; if (u?.last_input) return u.last_input; }
    return null;
  });
  // K4b: the same reply's parts (the stored object, so the selector stays stable).
  const parts = useArslanStore((s): ContextParts | null => {
    for (let i = s.items.length - 1; i >= 0; i--) { const u = s.items[i].usage; if (u?.last_input) return u.context_parts ?? null; }
    return null;
  });

  useEffect(() => {
    const onChanged = (e: Event) => {
      const d = (e as CustomEvent<{ conversationId: string; choice: ModelChoice | null }>).detail;
      if (d?.conversationId === conversationId) setChoiceState(d.choice);
    };
    window.addEventListener(MODEL_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(MODEL_CHANGED_EVENT, onChanged);
  }, [conversationId]);

  useEffect(() => { setChoiceState(null); }, [conversationId]);   // never show the last conversation's choice

  useEffect(() => {
    let alive = true;
    // Deferred into the promise so an unavailable client (offline, or a test's partial mock) is a rejection.
    Promise.resolve().then(() => conversationModelApi.get(conversationId))
      .then((r) => { if (alive) setChoiceState(r.choice ? { configId: r.choice.config_id, model: r.choice.model } : null); })
      .catch(() => {});
    return () => { alive = false; };
  }, [conversationId]);

  const primary = configs.find((c) => c.is_primary) ?? configs[0] ?? null;
  const current: ModelChoice | null = choice && configs.some((c) => c.id === choice.configId) ? choice
    : primary ? { configId: primary.id, model: primary.model } : null;

  useEffect(() => {
    if (!current) return;
    let alive = true;
    void catalog(current.configId).then((ms) => { if (alive) setWindow(ms.find((m) => m.id === current.model)?.context_window ?? null); });
    return () => { alive = false; };
  }, [current?.configId, current?.model]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Record this conversation's choice here and tell the other places showing it. */
  const setChoice = useCallback((next: ModelChoice | null) => {
    window.dispatchEvent(new CustomEvent(MODEL_CHANGED_EVENT, { detail: { conversationId, choice: next } }));
  }, [conversationId]);

  const pct = lastInput && window_ ? Math.round((lastInput / window_) * 100) : null;
  return { choice, setChoice, primary, current, window: window_, lastInput, parts, pct };
}
