/**
 * The settings PUT must carry ONLY the fields the user actually touched.
 *
 * 🔴 THIS IS A FAMILY, NOT AN INCIDENT. Three members so far, all the same shape —
 * the body is built from client state and therefore writes back fields nobody
 * edited, using a value that may not be what the server holds:
 *
 *   ① a MASKED key written back as the real secret     (looksMasked guards it)
 *   ② llm_strategy clobbered by an unhydrated default  (adapters.ts: "T6 FIX 1")
 *   ③ search_provider="tavily" on a fresh install      (broke keyless search)
 *
 * Each was fixed where it was found, per field. That kills the instance and leaves
 * the family: the next field added to AppSettings with a client-side default that
 * disagrees with the server becomes member four, and nothing here would notice.
 *
 * So the assertion is about the MECHANISM: a patch of one field produces a body of
 * one field. The backend does `model_dump(exclude_none=True)`, so an omitted field
 * is simply not written — partial bodies are the supported shape, not a trick.
 */
import { describe, expect, it } from "vitest";

import { toBackendSettingsPatch } from "../api/adapters";

describe("a patch of one field is a body of one field", () => {
  it("sends language and nothing else", () => {
    const body = toBackendSettingsPatch({ language: "zh" });
    expect(body).toEqual({ language: "zh" });
  });

  it("cannot smuggle search_provider — family member ③", () => {
    // The exact regression: a fresh install shows the API's default, the user
    // changes the language, and the body used to carry the provider too.
    const body = toBackendSettingsPatch({ language: "en" });
    expect(body).not.toHaveProperty("search_provider");
  });

  it("cannot smuggle llm_strategy — family member ②", () => {
    const body = toBackendSettingsPatch({ language: "en" });
    expect(body).not.toHaveProperty("llm_strategy");
  });

  it("cannot smuggle a key the user did not retype — family member ①", () => {
    const body = toBackendSettingsPatch({ language: "en" });
    expect(body).not.toHaveProperty("search_api_key");
    expect(body).not.toHaveProperty("github_token");
  });
});

describe("what IS touched still travels correctly", () => {
  it("maps camelCase to the backend name", () => {
    expect(toBackendSettingsPatch({ llmStrategy: "balanced" })).toEqual({
      llm_strategy: "balanced",
    });
  });

  it("carries the booleans in the shapes the backend expects", () => {
    expect(toBackendSettingsPatch({ evolutionAuto: true })).toEqual({ evolution_auto: "on" });
    expect(toBackendSettingsPatch({ evolutionAuto: false })).toEqual({ evolution_auto: "off" });
    expect(toBackendSettingsPatch({ orchestratorShellEnabled: true })).toEqual({
      orchestrator_shell_enabled: "true",
    });
    expect(toBackendSettingsPatch({ mcpServerEnabled: true })).toEqual({
      mcp_server_enabled: true,
    });
  });

  it("sends an emptied slot as empty, which is how a slot is cleared", () => {
    expect(toBackendSettingsPatch({ visionConfigId: "" })).toEqual({ vision_config_id: "" });
  });

  it("sends a real key the user typed", () => {
    expect(toBackendSettingsPatch({ apiKeySearch: "tvly-realkey123" })).toEqual({
      search_api_key: "tvly-realkey123",
    });
  });

  it("still omits a masked key even when it IS in the patch", () => {
    // The mask guard is not made redundant by the patch shape: a key field can be
    // in the patch because the user focused and blurred it without editing, and
    // its displayed value is the mask.
    expect(toBackendSettingsPatch({ apiKeySearch: "sk-...wxyz" })).toEqual({});
    expect(toBackendSettingsPatch({ githubToken: "***" })).toEqual({});
  });

  it("carries several touched fields together", () => {
    expect(toBackendSettingsPatch({ language: "ja", curationEnabled: true })).toEqual({
      language: "ja",
      curation_enabled: true,
    });
  });
});

describe("every settings field the UI can edit is mappable", () => {
  it("maps each key the full-body adapter knows about", async () => {
    // 🔴 Derived, not hand-listed. A hand-written list of fields is the thing that
    // rots: this walks what the full-body adapter produces and requires the patch
    // adapter to know every one of them, so a field added to one and not the other
    // fails here instead of silently never saving.
    const { toBackendSettings } = await import("../api/adapters");
    const full = toBackendSettings({
      searchProvider: "duckduckgo",
      searchBaseUrl: "",
      apiKeySearch: "",
      githubToken: "",
      language: "en",
      llmStrategy: "single",
      distillOnSessionEnd: true,
      orchestratorShellEnabled: false,
      shellConfirmPolicy: "ask_all",
      mcpServerEnabled: false,
    } as never);

    const uiNameFor: Record<string, unknown> = {
      search_provider: { searchProvider: "duckduckgo" },
      search_base_url: { searchBaseUrl: "http://x" },
      language: { language: "en" },
      llm_strategy: { llmStrategy: "single" },
      distill_on_session_end: { distillOnSessionEnd: true },
      orchestrator_shell_enabled: { orchestratorShellEnabled: false },
      shell_confirm_policy: { shellConfirmPolicy: "ask_all" },
      embedding_config_id: { embeddingConfigId: "1" },
      synthesis_config_id: { synthesisConfigId: "1" },
      compaction_config_id: { compactionConfigId: "1" },
      title_config_id: { titleConfigId: "1" },
      router_config_id: { routerConfigId: "1" },
      vision_config_id: { visionConfigId: "1" },
      curation_enabled: { curationEnabled: true },
      evolution_auto: { evolutionAuto: true },
      evolution_max_dispatches: { evolutionMaxDispatches: 5 },
      ocr_languages: { ocrLanguages: "eng" },
      run_debug_retention_days: { runDebugRetentionDays: 30 },
      mcp_server_enabled: { mcpServerEnabled: true },
      workspace_dir: { workspaceDir: "/tmp/ws" },
      heartbeat_enabled: { heartbeatEnabled: true },
      heartbeat_checklist: { heartbeatChecklist: "- x" },
    };

    const unmappable: string[] = [];
    for (const backendKey of Object.keys(full)) {
      const patch = uiNameFor[backendKey];
      if (!patch) {
        unmappable.push(`${backendKey} (no case in this test — add one)`);
        continue;
      }
      const out = toBackendSettingsPatch(patch as never);
      if (!(backendKey in out)) unmappable.push(backendKey);
    }
    expect(unmappable).toEqual([]);
  });
});


describe("the save path actually uses it", () => {
  it("builds the PUT from the patch, not from live settings", async () => {
    // A patch adapter nobody calls is the family still shipping with better
    // structure. The forbidden line is the old one: a body built from
    // {...settingsRef.current, ...pending}.
    const src = await import("../hooks/useDebouncedSettingsSave?raw");
    const text = src.default as string;
    expect(text).toMatch(/toBackendSettingsPatch\(source\)/);
    expect(text).not.toMatch(/\{ \.\.\.settingsRef\.current, \.\.\.pending \}/);
  });
});
