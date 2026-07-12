/**
 * useDebouncedSettingsSave — unit tests (Settings-T6).
 *
 * Covers the persistence-unification contract that replaces the top Save button:
 *  - non-key changes are DEBOUNCED and rapid changes collapse into ONE merged PUT;
 *  - flushField() persists IMMEDIATELY (key-field blur) and cancels any pending debounce;
 *  - a PUT failure reverts the optimistic value + surfaces status='error';
 *  - the transient 'saved' status appears then clears;
 *  - the empty/masked search-key invariant (toBackendSettings) is preserved;
 *  - a debounced NON-key save never carries a mid-typed (un-blurred) key field
 *    — this is the user's hard "key fields save on blur only" constraint at the hook level.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook } from "@testing-library/react";

// ── api mock ────────────────────────────────────────────────────────────────
const mockUpdateSettings = vi.fn().mockResolvedValue({});
vi.mock("../api/client", () => ({
  api: {
    updateSettings: (...args: unknown[]) => mockUpdateSettings(...args),
  },
}));

import { useDebouncedSettingsSave } from "../hooks/useDebouncedSettingsSave";
import type { AppSettings } from "../types";

const base: AppSettings = {
  searchProvider: "tavily",
  apiKeySearch: "tvly-••••",
  githubToken: "",
  language: "en",
  theme: "dark",
  telemetry: false,
  spawnMode: "auto",
  llmStrategy: "single",
  distillOnSessionEnd: true,
  orchestratorShellEnabled: false,
  shellConfirmPolicy: "ask_all",
  embeddingConfigId: "",
  runDebugRetentionDays: 30,
};

/**
 * Drives the hook with a stateful `settings` that the returned setter mutates,
 * mirroring SettingsScreen's localSettings — so optimistic updates and reverts
 * are observable across rerenders.
 */
function setupHook(overrides: Partial<AppSettings> = {}, opts: { enabled?: boolean } = {}) {
  let settings: AppSettings = { ...base, ...overrides };
  const onPersisted = vi.fn();
  const setLocalSettings = vi.fn((updater: AppSettings | ((p: AppSettings) => AppSettings)) => {
    settings = typeof updater === "function" ? (updater as (p: AppSettings) => AppSettings)(settings) : updater;
    rerender({ settings, setLocalSettings, onPersisted, enabled: opts.enabled ?? true, debounceMs: 600, savedLingerMs: 2000 });
  });
  const { result, rerender } = renderHook(
    (props) => useDebouncedSettingsSave(props),
    { initialProps: { settings, setLocalSettings, onPersisted, enabled: opts.enabled ?? true, debounceMs: 600, savedLingerMs: 2000 } },
  );
  return { result, getSettings: () => settings, onPersisted, setLocalSettings };
}

describe("useDebouncedSettingsSave", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockUpdateSettings.mockClear();
    mockUpdateSettings.mockResolvedValue({});
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("collapses rapid non-key changes into exactly ONE debounced PUT with the merged body", async () => {
    const { result } = setupHook();
    act(() => {
      result.current.saveField({ searchProvider: "serpapi" });
      result.current.saveField({ distillOnSessionEnd: false });
      result.current.saveField({ orchestratorShellEnabled: true });
    });
    // Nothing fires before the debounce elapses.
    expect(mockUpdateSettings).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    const body = mockUpdateSettings.mock.calls[0][0];
    expect(body.search_provider).toBe("serpapi");
    expect(body.distill_on_session_end).toBe(false);
    expect(body.orchestrator_shell_enabled).toBe("true");
  });

  it("optimistically applies the change to localSettings immediately", () => {
    const { result, getSettings } = setupHook();
    act(() => {
      result.current.saveField({ searchProvider: "serpapi" });
    });
    expect(getSettings().searchProvider).toBe("serpapi");
  });

  it("flushField() PUTs immediately and cancels a pending debounce (key-field blur)", async () => {
    const { result } = setupHook();
    act(() => {
      result.current.saveField({ telemetry: true }); // schedules a debounce
      result.current.editKeyField("apiKeySearch", "tvly-new"); // user edits the key
      result.current.flushField({ apiKeySearch: "tvly-new" }); // blur → immediate
    });
    // Immediate PUT already happened once (the flush), no debounce yet.
    await act(async () => {
      await Promise.resolve();
    });
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    // Advancing past the debounce window must NOT trigger a second PUT.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    const body = mockUpdateSettings.mock.calls[0][0];
    expect(body.search_api_key).toBe("tvly-new");
  });

  it("does NOT send the search key on a non-key debounced save (blur-only key constraint)", async () => {
    // The user typed a real key into localSettings but has NOT blurred it.
    const { result } = setupHook({ apiKeySearch: "tvly-typed-but-not-blurred" });
    act(() => {
      result.current.saveField({ telemetry: true });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    const body = mockUpdateSettings.mock.calls[0][0];
    expect(body.search_api_key).toBeUndefined();
  });

  it("does NOT send an empty/masked search key (toBackendSettings invariant preserved)", async () => {
    const { result } = setupHook({ apiKeySearch: "" });
    act(() => {
      result.current.saveField({ searchProvider: "serpapi" });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    const body = mockUpdateSettings.mock.calls[0][0];
    expect(body.search_api_key).toBeUndefined();
  });

  it("reverts the optimistic value and surfaces status='error' when the PUT fails", async () => {
    mockUpdateSettings.mockRejectedValueOnce(new Error("boom"));
    const { result, getSettings } = setupHook();
    act(() => {
      result.current.saveField({ searchProvider: "serpapi" });
    });
    expect(getSettings().searchProvider).toBe("serpapi"); // optimistic
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("boom");
    // reverted back to the pre-change value
    expect(getSettings().searchProvider).toBe("tavily");
  });

  it("shows a transient 'saved' status that clears after the linger window", async () => {
    const { result } = setupHook();
    act(() => {
      result.current.saveField({ searchProvider: "serpapi" });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(result.current.status).toBe("saved");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(result.current.status).toBe("idle");
  });

  it("no-ops the PUT when disabled (offline) but still applies the optimistic display value", async () => {
    const { result, getSettings } = setupHook({}, { enabled: false });
    act(() => {
      result.current.saveField({ searchProvider: "serpapi" });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(mockUpdateSettings).not.toHaveBeenCalled();
    expect(getSettings().searchProvider).toBe("serpapi");
  });

  // ── FIX 2: dirty-guard key blur-save ────────────────────────────────────────
  it("does NOT PUT on an unedited key blur (dirty-guard)", async () => {
    const { result } = setupHook({ apiKeySearch: "tv...bcde" });
    act(() => {
      result.current.flushField({ apiKeySearch: "tv...bcde" }); // tab-through, never edited
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(mockUpdateSettings).not.toHaveBeenCalled();
  });

  it("PUTs on blur after the key was edited, and that field is no longer dirty afterwards", async () => {
    const { result } = setupHook();
    act(() => {
      result.current.editKeyField("apiKeySearch", "tvly-new");
      result.current.flushField({ apiKeySearch: "tvly-new" });
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    expect(mockUpdateSettings.mock.calls[0][0].search_api_key).toBe("tvly-new");
    // A second, unedited blur must NOT re-PUT (dirty was cleared on success).
    act(() => {
      result.current.flushField({ apiKeySearch: "tvly-new" });
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
  });

  it("keeps the typed key value on a failed key save (never reverts to the mask)", async () => {
    mockUpdateSettings.mockRejectedValueOnce(new Error("boom"));
    const { result, getSettings } = setupHook({ apiKeySearch: "tv...bcde" }); // starts masked
    act(() => {
      result.current.editKeyField("apiKeySearch", "tvly-typed");
      result.current.flushField({ apiKeySearch: "tvly-typed" });
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.status).toBe("error");
    // The user's typed value survives — NOT rolled back to the mask placeholder.
    expect(getSettings().apiKeySearch).toBe("tvly-typed");
  });

  // ── FIX 3: latest-wins PUT sequencing ───────────────────────────────────────
  it("ignores a stale in-flight PUT that settles after a newer one (latest-wins)", async () => {
    let rejectA!: (e: unknown) => void;
    mockUpdateSettings
      .mockImplementationOnce(() => new Promise((_res, rej) => { rejectA = rej; })) // A hangs
      .mockImplementationOnce(() => Promise.resolve({})); // B resolves
    const { result, getSettings } = setupHook();

    // Issue A (searchProvider) — goes in-flight and hangs.
    act(() => {
      result.current.saveField({ searchProvider: "serpapi" });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(result.current.status).toBe("saving");

    // Issue B (language) — resolves.
    act(() => {
      result.current.saveField({ language: "ja" });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(result.current.status).toBe("saved");

    // A rejects late — its rollback/status must be ignored (superseded).
    await act(async () => {
      rejectA(new Error("late-A"));
      await Promise.resolve();
    });
    expect(result.current.status).toBe("saved");
    expect(result.current.error).toBeNull();
    expect(getSettings().searchProvider).toBe("serpapi"); // A's revert ignored
    expect(getSettings().language).toBe("ja");
  });
});
