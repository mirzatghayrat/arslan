/**
 * useDebouncedSettingsSave — the single owner of the debounced PUT /settings for
 * the settings-table fields (Settings-T6). Replaces the old top-level Save
 * button + `<form onSubmit>` flow with instant auto-save:
 *
 *  - saveField(patch): NON-key fields. Merges into a pending buffer, debounces
 *    (~600ms) and then PUTs once — multiple rapid changes collapse into ONE PUT.
 *  - editKeyField(field, value): KEY fields (search key / GitHub token) onChange —
 *    updates the display value AND marks the field dirty. No persistence here.
 *  - flushField(patch): KEY fields on blur. Cancels any pending debounce and PUTs
 *    immediately, BUT only if the key was actually edited (dirty) — an unedited
 *    blur is a no-op. This is the user's hard constraint: key-type fields persist
 *    on BLUR only, never per-keystroke, and never on a bare tab-through.
 *
 * Optimistic + rollback: every change is applied to localSettings immediately so
 * the UI reflects it; for NON-key fields the pre-change value is snapshotted and
 * reverted on PUT rejection. KEY fields are NEVER reverted — their pre-edit value
 * is the mask placeholder, so on a key-save failure we keep the user's typed
 * value + surface the error (they retry on the next blur; the field stays dirty).
 *
 * Empty/masked-key invariant: the body is always built via toBackendSettings,
 * which omits an empty or masked secret. Additionally, a NON-key debounced PUT
 * blanks the key fields it is not explicitly flushing, so a mid-typed (un-blurred)
 * key can never ride out on a non-key save.
 *
 * Sequencing (latest-wins): each PUT captures a monotonic request version; when a
 * PUT settles, if a newer PUT has since been issued the stale one's status /
 * rollback / persist effects are ignored — so a slow in-flight save can't clobber
 * a newer one that already resolved.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type React from "react";
import { api } from "../api/client";
import { toBackendSettingsPatch } from "../api/adapters";
import type { AppSettings } from "../types";

export type SettingsSaveStatus = "idle" | "saving" | "saved" | "error";

/** Secret-ish fields that persist on blur only (see editKeyField / flushField). */
const KEY_FIELDS: (keyof AppSettings)[] = ["apiKeySearch", "githubToken"];
const isKeyField = (k: string): k is keyof AppSettings =>
  (KEY_FIELDS as string[]).includes(k);
const DEFAULT_DEBOUNCE_MS = 600;
const DEFAULT_SAVED_LINGER_MS = 2000;

export interface UseDebouncedSettingsSaveArgs {
  /** The working copy of settings (SettingsScreen's localSettings). */
  settings: AppSettings;
  /** Setter for the working copy — used for optimistic apply + rollback. */
  setLocalSettings: React.Dispatch<React.SetStateAction<AppSettings>>;
  /**
   * Called after a successful PUT with ONLY the fields that were actually
   * persisted (a patch), so the parent merges just those — untouched key fields
   * (which may hold a mask placeholder) are never pushed back into the parent.
   */
  onPersisted?: (persisted: Partial<AppSettings>) => void;
  /**
   * When false (backend offline) the PUT is skipped and the change is BUFFERED;
   * the optimistic display still applies, and a flip back to true re-flushes the
   * buffer (offline edits are not silently lost).
   */
  enabled?: boolean;
  /** Debounce window for non-key saves. */
  debounceMs?: number;
  /** How long the transient 'saved' status lingers before fading to 'idle'. */
  savedLingerMs?: number;
}

export interface UseDebouncedSettingsSave {
  /** Non-key fields: debounced, merged, single PUT. */
  saveField: (patch: Partial<AppSettings>) => void;
  /** Key-field onChange: display update + mark dirty (no persistence). */
  editKeyField: (field: keyof AppSettings, value: string) => void;
  /** Key fields on blur: PUT immediately, but only if the key is dirty. */
  flushField: (patch: Partial<AppSettings>) => void;
  /**
   * Key fields the user is actively editing (dirty). The host's settings-sync
   * effect consults this to avoid clobbering an in-progress key with the masked
   * value from a background save's settings round-trip.
   */
  getEditingKeyFields: () => (keyof AppSettings)[];
  status: SettingsSaveStatus;
  error: string | null;
}

export function useDebouncedSettingsSave({
  settings,
  setLocalSettings,
  onPersisted,
  enabled = true,
  debounceMs = DEFAULT_DEBOUNCE_MS,
  savedLingerMs = DEFAULT_SAVED_LINGER_MS,
}: UseDebouncedSettingsSaveArgs): UseDebouncedSettingsSave {
  const [status, setStatus] = useState<SettingsSaveStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  // Live mirror of the latest settings so a debounced PUT that fires several
  // renders later never closes over a stale snapshot.
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  // Latest wiring — kept in refs so the stable callbacks don't need to re-bind.
  const onPersistedRef = useRef(onPersisted);
  onPersistedRef.current = onPersisted;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  // Accumulated pending patch (collapses rapid changes) + pre-change snapshot
  // for rollback (NON-key fields only). Distinct object identities per batch
  // avoid cross-contamination with an in-flight PUT.
  const pendingRef = useRef<Partial<AppSettings>>({});
  const revertRef = useRef<Partial<AppSettings>>({});

  // Which key fields the user has actually edited since the last successful save.
  const dirtyKeysRef = useRef<Set<keyof AppSettings>>(new Set());

  // Monotonic PUT version — latest-wins settle ordering (FIX 3).
  const requestSeqRef = useRef(0);

  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (debounceTimer.current !== null) clearTimeout(debounceTimer.current);
      if (savedTimer.current !== null) clearTimeout(savedTimer.current);
    };
  }, []);

  const scheduleSavedFade = useCallback(() => {
    if (savedTimer.current !== null) clearTimeout(savedTimer.current);
    savedTimer.current = setTimeout(() => {
      savedTimer.current = null;
      // Only fade if nothing else started saving in the meantime.
      setStatus((s) => (s === "saved" ? "idle" : s));
    }, savedLingerMs);
  }, [savedLingerMs]);

  const runPut = useCallback(async () => {
    // Offline — keep the buffer intact so the reconnect effect can flush it.
    if (!enabledRef.current) return;
    const pending = pendingRef.current;
    if (Object.keys(pending).length === 0) return;
    const revert = revertRef.current;
    // New batch objects — an edit landing during the await accumulates cleanly.
    pendingRef.current = {};
    revertRef.current = {};

    // 🔴 ONLY what this batch actually touched. The body used to be the whole of
    // live settings merged with the patch, and blanking the key fields kept the
    // secrets out — but every OTHER field still rode along, carrying a client-side
    // value that could disagree with what the server holds. Three bugs came out of
    // that shape (a masked key written back as real; llm_strategy clobbered by an
    // unhydrated default; search_provider="tavily" on a fresh install, which broke
    // keyless search as soon as the user changed anything). Each was fixed per
    // field, which kills the instance and leaves the shape. Sending the patch
    // removes the shape: the backend does model_dump(exclude_none=True), so a
    // field that is not sent is not written.
    const source = pending;

    const seq = requestSeqRef.current + 1;
    requestSeqRef.current = seq;
    setStatus("saving");
    setError(null);
    try {
      await api.updateSettings(toBackendSettingsPatch(source));
      if (seq !== requestSeqRef.current) return; // superseded by a newer PUT → ignore
      // Committed successfully → those key fields are no longer dirty.
      for (const kf of KEY_FIELDS) {
        if (kf in pending) dirtyKeysRef.current.delete(kf);
      }
      // Propagate ONLY the persisted patch — the parent merges just these fields,
      // so a background non-key save never pushes a masked key back to the parent.
      onPersistedRef.current?.(pending);
      setStatus("saved");
      scheduleSavedFade();
    } catch (err) {
      if (seq !== requestSeqRef.current) return; // superseded → ignore stale rollback/status
      // Roll NON-key optimistic values back to their pre-change snapshot. Key
      // fields are absent from `revert` (never snapshotted) so the user's typed
      // value survives a failed key save for retry.
      setLocalSettings((prev) => ({ ...prev, ...revert }));
      setError(err instanceof Error ? err.message : "Save failed");
      setStatus("error");
    }
  }, [scheduleSavedFade, setLocalSettings]);

  // Snapshot pre-change values for rollback — NON-key fields only (key fields are
  // never reverted; see the module doc + FIX note #4).
  const snapshot = useCallback((patch: Partial<AppSettings>) => {
    const revert = revertRef.current as unknown as Record<string, unknown>;
    for (const k of Object.keys(patch) as (keyof AppSettings)[]) {
      if (isKeyField(k)) continue;
      if (!(k in revertRef.current)) {
        revert[k as string] = settingsRef.current[k];
      }
    }
  }, []);

  const saveField = useCallback(
    (patch: Partial<AppSettings>) => {
      // Optimistic display update always applies (control stays responsive even
      // offline). The change is ALWAYS buffered (snapshot + pending) so an offline
      // edit isn't lost — only the network debounce is gated on `enabled`.
      setLocalSettings((prev) => ({ ...prev, ...patch }));
      snapshot(patch);
      pendingRef.current = { ...pendingRef.current, ...patch };
      if (!enabledRef.current) return; // offline: buffered, flushed on reconnect
      if (debounceTimer.current !== null) clearTimeout(debounceTimer.current);
      debounceTimer.current = setTimeout(() => {
        debounceTimer.current = null;
        void runPut();
      }, debounceMs);
    },
    [debounceMs, runPut, setLocalSettings, snapshot],
  );

  const editKeyField = useCallback(
    (field: keyof AppSettings, value: string) => {
      // Display-only: no persistence until blur. Marks the field dirty so the
      // subsequent blur actually flushes (an unedited blur must not PUT).
      dirtyKeysRef.current.add(field);
      setLocalSettings((prev) => ({ ...prev, [field]: value }));
    },
    [setLocalSettings],
  );

  const flushField = useCallback(
    (patch: Partial<AppSettings>) => {
      const patchKeys = Object.keys(patch);
      const hasNonKey = patchKeys.some((k) => !isKeyField(k));
      const dirtyKeyFields = patchKeys.filter(
        (k) => isKeyField(k) && dirtyKeysRef.current.has(k),
      );
      // Unedited key blur (only clean key fields, nothing else) → nothing to
      // persist. Skip entirely — no display churn, no PUT.
      if (!hasNonKey && dirtyKeyFields.length === 0) return;

      setLocalSettings((prev) => ({ ...prev, ...patch }));
      snapshot(patch);
      pendingRef.current = { ...pendingRef.current, ...patch };
      if (!enabledRef.current) return; // offline: buffered, flushed on reconnect
      if (debounceTimer.current !== null) {
        clearTimeout(debounceTimer.current);
        debounceTimer.current = null;
      }
      void runPut();
    },
    [runPut, setLocalSettings, snapshot],
  );

  const getEditingKeyFields = useCallback(
    (): (keyof AppSettings)[] => Array.from(dirtyKeysRef.current),
    [],
  );

  // Reconnect flush — when `enabled` flips false→true, flush anything buffered
  // while offline exactly once (no Save button to fall back on).
  const wasEnabledRef = useRef(enabled);
  useEffect(() => {
    if (enabled && !wasEnabledRef.current && Object.keys(pendingRef.current).length > 0) {
      void runPut();
    }
    wasEnabledRef.current = enabled;
  }, [enabled, runPut]);

  return { saveField, editKeyField, flushField, getEditingKeyFields, status, error };
}
