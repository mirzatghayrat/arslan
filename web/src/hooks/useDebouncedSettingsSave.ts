/**
 * useDebouncedSettingsSave — the single owner of the debounced PUT /settings for
 * the settings-table fields (Settings-T6). Replaces the old top-level Save
 * button + `<form onSubmit>` flow with instant auto-save:
 *
 *  - saveField(patch): NON-key fields. Merges into a pending buffer, debounces
 *    (~600ms) and then PUTs once — multiple rapid changes collapse into ONE PUT.
 *  - flushField(patch): KEY fields on blur (search key / GitHub token). Cancels
 *    any pending debounce and PUTs immediately. This is the mechanism behind the
 *    user's hard constraint: key-type fields persist on BLUR only, never per key-
 *    stroke (their onChange updates the display value; only blur reaches here).
 *
 * Optimistic + rollback: every change is applied to localSettings immediately so
 * the UI reflects it; the pre-change value is snapshotted, and on PUT rejection
 * the optimistic value is reverted and status flips to 'error' (mirrors
 * ProviderConfigList's optimistic field handlers).
 *
 * Empty/masked-key invariant: the body is always built via toBackendSettings,
 * which omits an empty or masked search key / GitHub token. Additionally, a NON-
 * key debounced PUT blanks the key fields it is not explicitly flushing, so a
 * mid-typed (un-blurred) key can never ride out on a non-key save.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type React from "react";
import { api } from "../api/client";
import { toBackendSettings } from "../api/adapters";
import type { AppSettings } from "../types";

export type SettingsSaveStatus = "idle" | "saving" | "saved" | "error";

/** Secret-ish fields that persist on blur only (see flushField). */
const KEY_FIELDS: (keyof AppSettings)[] = ["apiKeySearch", "githubToken"];
const DEFAULT_DEBOUNCE_MS = 600;
const DEFAULT_SAVED_LINGER_MS = 2000;

export interface UseDebouncedSettingsSaveArgs {
  /** The working copy of settings (SettingsScreen's localSettings). */
  settings: AppSettings;
  /** Setter for the working copy — used for optimistic apply + rollback. */
  setLocalSettings: React.Dispatch<React.SetStateAction<AppSettings>>;
  /** Called with the merged settings after a successful PUT (propagate to parent). */
  onPersisted?: (next: AppSettings) => void;
  /** When false (backend offline) the PUT is skipped; the optimistic display still applies. */
  enabled?: boolean;
  /** Debounce window for non-key saves. */
  debounceMs?: number;
  /** How long the transient 'saved' status lingers before fading to 'idle'. */
  savedLingerMs?: number;
}

export interface UseDebouncedSettingsSave {
  /** Non-key fields: debounced, merged, single PUT. */
  saveField: (patch: Partial<AppSettings>) => void;
  /** Key fields on blur: cancel pending debounce, PUT immediately. */
  flushField: (patch: Partial<AppSettings>) => void;
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
  // for rollback. Distinct object identities per batch avoid cross-contamination
  // with an in-flight PUT.
  const pendingRef = useRef<Partial<AppSettings>>({});
  const revertRef = useRef<Partial<AppSettings>>({});

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
    const pending = pendingRef.current;
    if (Object.keys(pending).length === 0) return;
    const revert = revertRef.current;
    // New batch objects — an edit landing during the await accumulates cleanly.
    pendingRef.current = {};
    revertRef.current = {};

    // Full body from live settings + this batch's patch. Key fields NOT part of
    // this flush are blanked so toBackendSettings omits them (backend keeps the
    // stored secret) — this is what makes a non-key PUT unable to carry a key.
    const source: AppSettings = { ...settingsRef.current, ...pending };
    const mutableSource = source as unknown as Record<string, unknown>;
    for (const kf of KEY_FIELDS) {
      if (!(kf in pending)) {
        mutableSource[kf as string] = "";
      }
    }
    const merged: AppSettings = { ...settingsRef.current, ...pending };

    setStatus("saving");
    setError(null);
    try {
      await api.updateSettings(toBackendSettings(source));
      onPersistedRef.current?.(merged);
      setStatus("saved");
      scheduleSavedFade();
    } catch (err) {
      // Roll the optimistic values back to their pre-change snapshot.
      setLocalSettings((prev) => ({ ...prev, ...revert }));
      setError(err instanceof Error ? err.message : "Save failed");
      setStatus("error");
    }
  }, [scheduleSavedFade, setLocalSettings]);

  const snapshot = useCallback((patch: Partial<AppSettings>) => {
    const revert = revertRef.current as unknown as Record<string, unknown>;
    for (const k of Object.keys(patch) as (keyof AppSettings)[]) {
      if (!(k in revertRef.current)) {
        revert[k as string] = settingsRef.current[k];
      }
    }
  }, []);

  const saveField = useCallback(
    (patch: Partial<AppSettings>) => {
      // Optimistic display update always applies (control stays responsive even
      // offline); only persistence is gated on `enabled`.
      setLocalSettings((prev) => ({ ...prev, ...patch }));
      if (!enabledRef.current) return;
      snapshot(patch);
      pendingRef.current = { ...pendingRef.current, ...patch };
      if (debounceTimer.current !== null) clearTimeout(debounceTimer.current);
      debounceTimer.current = setTimeout(() => {
        debounceTimer.current = null;
        void runPut();
      }, debounceMs);
    },
    [debounceMs, runPut, setLocalSettings, snapshot],
  );

  const flushField = useCallback(
    (patch: Partial<AppSettings>) => {
      setLocalSettings((prev) => ({ ...prev, ...patch }));
      if (!enabledRef.current) return;
      snapshot(patch);
      pendingRef.current = { ...pendingRef.current, ...patch };
      if (debounceTimer.current !== null) {
        clearTimeout(debounceTimer.current);
        debounceTimer.current = null;
      }
      void runPut();
    },
    [runPut, setLocalSettings, snapshot],
  );

  return { saveField, flushField, status, error };
}
