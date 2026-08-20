import { describe, it, expect } from "vitest";
import { toUiSpawn, toUiSettings, toUiMessages, toBackendSettings } from "../api/adapters";
import type { ArslanThreadItem } from "../api/client.types";
import type { AppSettings as BackendAppSettings } from "../api/client.types";

// ── toUiSpawn ─────────────────────────────────────────────────────────────────

describe("toUiSpawn", () => {
  it("maps a backend spawn to the UI Spawn shape", () => {
    const api = { id: 7, name: "Aletheia", domain: "finance", description: "d", status: "idle", tools: ["web_search"], skills: ["financial-res"], total_tasks: 42 };
    const ui = toUiSpawn(api as never);
    expect(ui).toMatchObject({ id: "7", name: "Aletheia", status: "idle", totalTasks: 42 });
    expect(ui.tools).toContain("web_search");
  });

  it("stringifies numeric id", () => {
    const api = { id: 1, name: "X", domain: "general", capabilities: [], template_used: null, generation_level: 0, created_at: "", updated_at: "" };
    expect(toUiSpawn(api).id).toBe("1");
  });

  it("falls back to capabilities when tools absent", () => {
    const api = { id: 2, name: "Y", domain: "ops", capabilities: ["cap_a", "cap_b"], template_used: null, generation_level: 0, created_at: "", updated_at: "" };
    const ui = toUiSpawn(api);
    expect(ui.tools).toEqual(["cap_a", "cap_b"]);
  });

  it("defaults status to idle", () => {
    const api = { id: 3, name: "Z", domain: "ops", capabilities: [], template_used: null, generation_level: 0, created_at: "", updated_at: "" };
    expect(toUiSpawn(api).status).toBe("idle");
  });

  it("defaults totalTasks to 0", () => {
    const api = { id: 4, name: "W", domain: "ops", capabilities: [], template_used: null, generation_level: 0, created_at: "", updated_at: "" };
    expect(toUiSpawn(api).totalTasks).toBe(0);
  });
});

// ── toUiSettings ─────────────────────────────────────────────────────────────

describe("toUiSettings", () => {
  const backendBase: BackendAppSettings = {
    llm_provider: "anthropic",
    llm_model: "claude-sonnet-4-5",
    llm_base_url: "https://api.anthropic.com",
    llm_api_key: "sk-ant-••••••••",
    language: "en",
    search_provider: "tavily",
    search_base_url: '',
    search_api_key: "tvly-••••••••",
    github_token: "",
  };

  it("maps snake_case backend fields to camelCase UI fields", () => {
    const ui = toUiSettings(backendBase);
    expect(ui.searchProvider).toBe("tavily");
    expect(ui.language).toBe("en");
  });

  it("legacy flat LLM fields are NOT mapped to UI (multi-config list is source of truth)", () => {
    const ui = toUiSettings(backendBase) as Record<string, unknown>;
    expect(ui.llmProvider).toBeUndefined();
    expect(ui.llmModel).toBeUndefined();
    expect(ui.apiKeyLLM).toBeUndefined();
  });

  it("passes through masked search key value as-is", () => {
    const ui = toUiSettings(backendBase);
    expect(ui.apiKeySearch).toBe("tvly-••••••••");
  });

  it("does NOT include theme, telemetry, spawnMode (UI-only fields)", () => {
    const ui = toUiSettings(backendBase) as Record<string, unknown>;
    expect(ui.theme).toBeUndefined();
    expect(ui.telemetry).toBeUndefined();
    expect(ui.spawnMode).toBeUndefined();
  });

  it("falls back to empty string when search_api_key is absent", () => {
    const partial = { ...backendBase, search_api_key: undefined as unknown as string };
    const ui = toUiSettings(partial);
    expect(ui.apiKeySearch).toBe("");
  });

  // ── T6 FIX 1: llm_strategy must round-trip (was never hydrated → auto-save
  // clobbered the stored value back to the 'single' default) ───────────────────
  it("hydrates llmStrategy from the backend llm_strategy field", () => {
    const ui = toUiSettings({ ...backendBase, llm_strategy: "balanced" });
    expect((ui as { llmStrategy: string }).llmStrategy).toBe("balanced");
  });

  it("defaults llmStrategy to 'single' when llm_strategy is absent", () => {
    const ui = toUiSettings(backendBase);
    expect((ui as { llmStrategy: string }).llmStrategy).toBe("single");
  });
});

// ── toBackendSettings (masked-key omission) ───────────────────────────────────

describe("toBackendSettings", () => {
  const baseUi: AppSettings = {
    searchProvider: "tavily",
    searchBaseUrl: '',
    apiKeySearch: "",
    githubToken: "",
    language: "en",
    theme: "dark",
    telemetry: false,
    spawnMode: "auto",
    llmStrategy: "single",
    distillOnSessionEnd: true,
    orchestratorShellEnabled: false,
    shellConfirmPolicy: "ask_all", workspaceDir: "",
    mcpServerEnabled: false,
  };

  it("omits search_api_key when empty", () => {
    const body = toBackendSettings({ ...baseUi, apiKeySearch: "" });
    expect(body.search_api_key).toBeUndefined();
  });

  it("omits search_api_key when masked (bullet pattern)", () => {
    const body = toBackendSettings({ ...baseUi, apiKeySearch: "••••••••" });
    expect(body.search_api_key).toBeUndefined();
  });

  it("includes search_api_key when user entered a real value", () => {
    const body = toBackendSettings({ ...baseUi, apiKeySearch: "tvly-real-key" });
    expect(body.search_api_key).toBe("tvly-real-key");
  });

  // ── T6 FIX 1: the backend's real mask shapes must be omitted too ─────────────
  // mask_secret() emits "***" (len<8) and "<2-3 prefix>...<last4>" (long). The
  // old bullet-only guard let these through, so blurring an unedited key wrote
  // the mask placeholder back as the stored key. Mirror backend _looks_masked.
  it.each([
    ["sk-...wxyz"], // sk- prefix (3) ... last4
    ["tv...bcde"], // 2-char prefix ... last4
    ["gh...2345"], // github-style prefix ... last4
    ["***"], // short-key mask
    ["••••"], // legacy bullet mask
  ])("omits search_api_key when it is the masked echo %s", (masked) => {
    const body = toBackendSettings({ ...baseUi, apiKeySearch: masked });
    expect(body.search_api_key).toBeUndefined();
  });

  it("still includes a real key that merely contains '...' but not the mask shape", () => {
    // A real key isn't prefix(2-3)...last4; the anchored regex must not eat it.
    const body = toBackendSettings({ ...baseUi, apiKeySearch: "sk-realkey123" });
    expect(body.search_api_key).toBe("sk-realkey123");
  });

  it("omits github_token when it is a masked echo (prefix...last4)", () => {
    const body = toBackendSettings({ ...baseUi, githubToken: "gh...2345" });
    expect(body.github_token).toBeUndefined();
  });

  it("includes github_token when the user entered a real value", () => {
    const body = toBackendSettings({ ...baseUi, githubToken: "ghp_realtoken" });
    expect(body.github_token).toBe("ghp_realtoken");
  });

  it("does NOT send legacy flat LLM fields (llm_provider / llm_model / llm_api_key)", () => {
    const body = toBackendSettings(baseUi) as Record<string, unknown>;
    expect(body.llm_provider).toBeUndefined();
    expect(body.llm_model).toBeUndefined();
    expect(body.llm_api_key).toBeUndefined();
  });

  it("always includes non-key fields", () => {
    const body = toBackendSettings(baseUi);
    expect(body.search_provider).toBe("tavily");
    expect(body.language).toBe("en");
    expect(body.llm_strategy).toBe("single");
  });

  // ── T6 FIX 1: a GET→hydrate→PUT round-trip must preserve the stored strategy,
  // so an auto-save where the user changed nothing does NOT downgrade it ────────
  it("round-trips llm_strategy through toUiSettings → toBackendSettings", () => {
    const backend = {
      llm_provider: "anthropic",
      language: "en",
      search_provider: "tavily",
      search_base_url: '',
      search_api_key: "tvly-••••••••",
      github_token: "",
      llm_strategy: "balanced",
    } as unknown as Parameters<typeof toUiSettings>[0];
    const ui = { ...baseUi, ...toUiSettings(backend) };
    const body = toBackendSettings(ui);
    expect(body.llm_strategy).toBe("balanced");
  });
});

// ── toUiMessages ─────────────────────────────────────────────────────────────

import type { AppSettings } from "../types";

describe("toUiMessages", () => {
  const userItem: ArslanThreadItem = {
    id: 1,
    kind: "message",
    role: "user",
    content: "Hello",
  };

  const arslanItem: ArslanThreadItem = {
    id: 2,
    kind: "message",
    role: "arslan",
    content: "Hi there",
  };

  const spawnItem: ArslanThreadItem = {
    id: 3,
    kind: "message",
    role: "spawn",
    content: "Fetched data",
    spawnName: "Aletheia",
    toolSteps: [
      { tool: "web_search", argsSummary: "query: markets", status: "ok", resultSummary: "found 5 results" },
    ],
  };

  const escalationItem: ArslanThreadItem = {
    id: 4,
    kind: "escalation",
    role: "spawn",
    content: "",
    escalation: {
      spawnId: 10,
      spawnName: "Aletheia",
      kind: "capability",
      need: "Need file access",
      status: "resolving",
      how: undefined,
      why: undefined,
    },
  };

  it("maps user message correctly", () => {
    const [msg] = toUiMessages([userItem]);
    expect(msg.sender).toBe("user");
    expect(msg.senderName).toBe("You");
    expect(msg.text).toBe("Hello");
    expect(msg.id).toBe("1");
  });

  it("maps arslan message correctly", () => {
    const [msg] = toUiMessages([arslanItem]);
    expect(msg.sender).toBe("arslan");
    expect(msg.senderName).toBe("Arslan");
    expect(msg.text).toBe("Hi there");
  });

  it("maps spawn message with toolActivity", () => {
    const [msg] = toUiMessages([spawnItem]);
    expect(msg.sender).toBe("spawn");
    expect(msg.senderName).toBe("Aletheia");
    expect(msg.text).toBe("Fetched data");
    expect(msg.toolActivity).toBeDefined();
    expect(msg.toolActivity?.toolName).toBe("web_search");
    expect(msg.toolActivity?.action).toBe("query: markets");
    expect(msg.toolActivity?.outputSummary).toBe("found 5 results");
    expect(msg.toolActivity?.status).toBe("completed");
  });

  it("surfaces a chart artifact even when render_chart is not the first tool step", () => {
    const item: ArslanThreadItem = {
      id: 9,
      kind: "message",
      role: "spawn",
      content: "Here is the trend",
      spawnName: "GitTrend",
      toolSteps: [
        { tool: "web_search", argsSummary: "query: stars", status: "ok", resultSummary: "5 results" },
        { tool: "render_chart", argsSummary: "type: line", status: "ok", resultSummary: "rendered line",
          artifactSvg: "<svg>CHART</svg>" },
      ],
    } as ArslanThreadItem;
    const [msg] = toUiMessages([item]);
    expect(msg.toolActivity?.artifactSvg).toBe("<svg>CHART</svg>");
  });

  it("surfaces a pptx artifact from a later tool step (live incident: deck generated but no download card)", () => {
    const item: ArslanThreadItem = {
      id: 10,
      kind: "message",
      role: "spawn",
      content: "PPT 已生成并交付",
      spawnName: "Deck Master",
      toolSteps: [
        { tool: "web_search", argsSummary: "query: okx", status: "ok", resultSummary: "5 results" },
        { tool: "render_deck", argsSummary: "13 slides", status: "ok", resultSummary: "已生成 PPTX",
          artifactPptx: { filename: "okx.pptx", bytesB64: "UEsDBA==", slides: 13 } },
      ],
    } as ArslanThreadItem;
    const [msg] = toUiMessages([item]);
    expect(msg.toolActivity?.artifactPptx?.filename).toBe("okx.pptx");
    expect(msg.toolActivity?.artifactPptx?.slides).toBe(13);
  });

  it("maps escalation item to spawn message with escalation card", () => {
    const [msg] = toUiMessages([escalationItem]);
    expect(msg.sender).toBe("spawn");
    expect(msg.text).toBe("");
    expect(msg.escalation).toBeDefined();
    expect(msg.escalation?.spawnName).toBe("Aletheia");
    expect(msg.escalation?.issue).toBe("Need file access");
    expect(msg.escalation?.status).toBe("arslan_resolving");
  });

  it("maps escalation with resolved status", () => {
    const item: ArslanThreadItem = {
      ...escalationItem,
      escalation: { ...escalationItem.escalation!, status: "resolved", how: "Granted" },
    };
    const [msg] = toUiMessages([item]);
    expect(msg.escalation?.status).toBe("resolved");
    expect(msg.escalation?.resolutionMessage).toBe("Granted");
  });

  it("maps escalation with refused status", () => {
    const item: ArslanThreadItem = {
      ...escalationItem,
      escalation: { ...escalationItem.escalation!, status: "refused", why: "Not allowed" },
    };
    const [msg] = toUiMessages([item]);
    expect(msg.escalation?.status).toBe("refused");
    expect(msg.escalation?.resolutionMessage).toBe("Not allowed");
  });

  it("maps system spawn_created item", () => {
    const sysItem: ArslanThreadItem = {
      id: 5,
      kind: "system",
      role: "arslan",
      content: "__SPAWN_CREATED__:Aletheia",
      equipment: {
        toolsets: [{ key: "web_search", name: "Web Search", status: "active", grant: "permanent" }],
        skills: [],
      },
      intro: "Meet Aletheia, your finance spawn.",
    };
    const [msg] = toUiMessages([sysItem]);
    expect(msg.sender).toBe("arslan");
    expect(msg.spawnIntro).toBeDefined();
    expect(msg.spawnIntro?.name).toBe("Aletheia");
    expect(msg.spawnIntro?.tools).toContain("web_search");
    expect(msg.text).toBe("Meet Aletheia, your finance spawn.");
  });

  it("handles fact item", () => {
    const factItem: ArslanThreadItem = {
      id: 6,
      kind: "fact",
      role: "arslan",
      content: "User prefers dark mode",
    };
    const [msg] = toUiMessages([factItem]);
    expect(msg.sender).toBe("arslan");
    expect(msg.text).toBe("User prefers dark mode");
  });

  it("processes multiple items preserving order", () => {
    const msgs = toUiMessages([userItem, arslanItem, spawnItem]);
    expect(msgs).toHaveLength(3);
    expect(msgs[0].sender).toBe("user");
    expect(msgs[1].sender).toBe("arslan");
    expect(msgs[2].sender).toBe("spawn");
  });
});
