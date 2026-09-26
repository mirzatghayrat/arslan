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
import { useSettingsStore } from "../stores/settingsStore";

const base: AppSettings = {
  searchProvider: "tavily",
  searchBaseUrl: '',
  apiKeySearch: "tvly-••••",
  githubToken: "",
  language: "en",
  theme: "dark",
  telemetry: false,
  spawnMode: "auto",
  llmStrategy: "single",
  distillOnSessionEnd: true,
  orchestratorShellEnabled: false,
  shellConfirmPolicy: "ask_all", workspaceDir: "", heartbeatEnabled: false, heartbeatChecklist: "", lanDiscoveryEnabled: false, sshEnabled: false, defaultReadEnabled: true, voiceOutputEnabled: false, voiceInputLocale: "", voiceMode: "push_to_talk", voiceEndpointSilenceMs: 900,
  embeddingConfigId: "",
  runDebugRetentionDays: 30,
  mcpServerEnabled: false,
};

/**
 * Drives the hook with a stateful `settings` that the returned setter mutates,
 * mirroring SettingsScreen's localSettings — so optimistic updates and reverts
 * are observable across rerenders.
 */
function setupHook(overrides: Partial<AppSettings> = {}, opts: { enabled?: boolean } = {}) {
  let settings: AppSettings = { ...base, ...overrides };
  let enabled = opts.enabled ?? true;
  const onPersisted = vi.fn();
  const props = () => ({ settings, setLocalSettings, onPersisted, enabled, debounceMs: 600, savedLingerMs: 2000 });
  const setLocalSettings = vi.fn((updater: AppSettings | ((p: AppSettings) => AppSettings)) => {
    settings = typeof updater === "function" ? (updater as (p: AppSettings) => AppSettings)(settings) : updater;
    rerender(props());
  });
  const { result, rerender } = renderHook(
    (p) => useDebouncedSettingsSave(p),
    { initialProps: props() },
  );
  const setEnabled = (v: boolean) => {
    enabled = v;
    rerender(props());
  };
  return { result, getSettings: () => settings, onPersisted, setLocalSettings, setEnabled };
}

describe("useDebouncedSettingsSave", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockUpdateSettings.mockClear();
    mockUpdateSettings.mockResolvedValue({});
    useSettingsStore.setState({ settings: {
      llm_provider: "", llm_model: "", llm_base_url: "", llm_api_key: "",
      language: "zh", search_provider: "", search_base_url: "", search_api_key: "",
      github_token: "", voice_input_locale: "",
    } });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("updates shared consumers from only the saved response fields, never unrelated response values", async () => {
    mockUpdateSettings.mockResolvedValue({ language: "ja", voice_input_locale: "fr-FR", github_token: "stale-mask" });
    const { result } = setupHook();
    await act(async () => result.current.flushField({ language: "ja" }));
    expect(useSettingsStore.getState().settings).toMatchObject({ language: "ja", voice_input_locale: "", github_token: "" });
  });

  it("keeps shared settings unchanged when saving fails", async () => {
    mockUpdateSettings.mockRejectedValue(new Error("offline"));
    const { result } = setupHook();
    await act(async () => result.current.flushField({ language: "ja" }));
    expect(useSettingsStore.getState().settings?.language).toBe("zh");
  });

  it("keeps a late obsolete response out of shared settings", async () => {
    let resolveOld!: (value: unknown) => void;
    mockUpdateSettings.mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve; }));
    mockUpdateSettings.mockResolvedValueOnce({ language: "de" });
    const { result } = setupHook();
    act(() => result.current.flushField({ language: "ja" }));
    await act(async () => result.current.flushField({ language: "de" }));
    await act(async () => resolveOld({ language: "ja" }));
    expect(useSettingsStore.getState().settings?.language).toBe("de");
  });

  it("uses the backend's masked value instead of copying an edited secret into the shared store", async () => {
    mockUpdateSettings.mockResolvedValue({ github_token: "sy...only" });
    const { result } = setupHook();
    act(() => result.current.editKeyField("githubToken", "synthetic-secret-only"));
    await act(async () => result.current.flushField({ githubToken: "synthetic-secret-only" }));
    expect(useSettingsStore.getState().settings?.github_token).toBe("sy...only");
  });

  it("flushes a language choice immediately without carrying an unblurred secret", async () => {
    const { result, onPersisted } = setupHook();
    act(() => result.current.editKeyField("githubToken", "synthetic-unblurred-secret"));
    await act(async () => result.current.flushField({ language: "de" }));
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    expect(mockUpdateSettings).toHaveBeenCalledWith({ language: "de" });
    expect(onPersisted).toHaveBeenCalledWith({ language: "de" });
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

  // ── FIX 3: offline edits buffer + reflush on reconnect ──────────────────────
  it("buffers an offline edit and flushes it exactly once when back online", async () => {
    const { result, setEnabled } = setupHook({}, { enabled: false });
    act(() => {
      result.current.saveField({ searchProvider: "serpapi" });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(mockUpdateSettings).not.toHaveBeenCalled(); // offline: buffered, no PUT

    act(() => {
      setEnabled(true); // reconnect
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(mockUpdateSettings).toHaveBeenCalledTimes(1);
    expect(mockUpdateSettings.mock.calls[0][0].search_provider).toBe("serpapi");
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
