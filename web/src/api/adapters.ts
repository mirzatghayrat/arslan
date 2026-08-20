import type { AppSettings, Message, Spawn, UiRun, UiRunDimension, UiRunStep } from "../types";
import type { AppSettings as BackendAppSettings, ArslanThreadItem, RunDetailDto, RunStepDto, SpawnSummary } from "./client.types";

// ── Settings adapters ─────────────────────────────────────────────────────────

// Masked-echo detection — mirrors the backend's settings_service._looks_masked
// so a GET→(blur)→PUT round-trip never writes a mask placeholder back as the
// real secret. mask_secret() emits two shapes:
//   "***"                              – short-key mask (len < 8)
//   "<2-3 char prefix>...<last 4>"     – long-key mask (e.g. "sk-...wxyz")
// We also keep the legacy pure-bullet form (never a real key). The prefix regex
// is anchored full-string so a real key that merely contains "..." passes.
const MASK_PREFIX_RE = /^.{2,3}\.\.\..{4}$/;
const MASK_BULLET_RE = /^[•*]+$/;

function looksMasked(value: string): boolean {
  return value === "***" || MASK_BULLET_RE.test(value) || MASK_PREFIX_RE.test(value);
}

/**
 * Maps a backend AppSettings (snake_case) → UI AppSettings (camelCase).
 *
 * Field mapping:
 *   search_provider → searchProvider
 *   search_base_url → searchBaseUrl (plain; unlike the key it is never masked)
 *   search_api_key  → apiKeySearch (may be "" or masked)
 *   language       → language
 *
 * Legacy flat LLM fields (llm_provider / llm_model / llm_api_key) are no longer
 * mapped to UI state — the multi-config provider list is the single source of truth.
 *
 * llmStrategy DOES have a backend counterpart (GET /settings returns llm_strategy,
 * defaulting to "single"). It MUST be hydrated here — otherwise localSettings keeps
 * the client default and every debounced auto-save PUTs llm_strategy:'single',
 * silently clobbering the user's stored routing strategy (T6 FIX 1).
 *
 * UI-only fields with no backend counterpart are kept at their current UI value
 * and therefore should NOT be overwritten on fetch; callers must merge:
 *   theme, telemetry, spawnMode
 */
export function toUiSettings(backend: BackendAppSettings): Omit<AppSettings, "theme" | "telemetry" | "spawnMode"> {
  return {
    searchProvider: backend.search_provider ?? "",
  searchBaseUrl: backend.search_base_url ?? "",
    apiKeySearch: backend.search_api_key ?? "",
    githubToken: backend.github_token ?? "",
    language: backend.language ?? "en",
    // Routing strategy round-trips through the backend (default "single").
    llmStrategy: (backend.llm_strategy ?? "single") as AppSettings["llmStrategy"],
    distillOnSessionEnd: backend.distill_on_session_end ?? true,
    // Backend stores these as strings ("true"/"false", "ask_all"/"ask_risky"),
    // both default OFF / most-cautious when absent.
    orchestratorShellEnabled: backend.orchestrator_shell_enabled === "true",
    shellConfirmPolicy: backend.shell_confirm_policy === "ask_risky" ? "ask_risky" : "ask_all",
    // Workspace for the file tools (P1). Empty = unset = tools not offered.
    workspaceDir: backend.workspace_dir ?? "",
    embeddingConfigId: backend.embedding_config_id ?? "",
  synthesisConfigId: backend.synthesis_config_id ?? "",
  compactionConfigId: backend.compaction_config_id ?? "",
  titleConfigId: backend.title_config_id ?? "",
  routerConfigId: backend.router_config_id ?? "",
  visionConfigId: backend.vision_config_id ?? "",
    curationEnabled: backend.curation_enabled ?? false,
    evolutionAuto: backend.evolution_auto === "on",
    evolutionMaxDispatches: backend.evolution_max_dispatches ?? null,
    ocrLanguages: backend.ocr_languages ?? '',
    runDebugRetentionDays: backend.run_debug_retention_days ?? 30,
    mcpServerEnabled: backend.mcp_server_enabled ?? false,
  };
}

/**
 * Maps UI AppSettings (camelCase) → backend body (snake_case) for PUT /api/v1/settings.
 *
 * Masked-key handling: if the user did NOT type a new key (value is empty or still
 * matches the masked sentinel pattern), we omit that field from the PUT body so the
 * backend keeps the existing stored value.
 */
/**
 * ONE mapping table, camelCase UI name -> how that field goes on the wire.
 *
 * 🔴 A single table because the defect family this guards against is exactly two
 * descriptions of the same field drifting apart. Adding a setting means adding one
 * row here; the patch adapter and the full-body adapter both read it.
 */
const SETTINGS_WIRE: Record<string, { key: keyof BackendAppSettings; to?: (v: unknown) => unknown }> = {
  searchProvider: { key: "search_provider" },
  searchBaseUrl: { key: "search_base_url", to: (v) => (v as string) ?? "" },
  language: { key: "language" },
  llmStrategy: { key: "llm_strategy" },
  distillOnSessionEnd: { key: "distill_on_session_end" },
  orchestratorShellEnabled: { key: "orchestrator_shell_enabled", to: (v) => (v ? "true" : "false") },
  shellConfirmPolicy: { key: "shell_confirm_policy" },
  workspaceDir: { key: "workspace_dir", to: (v) => (v as string) ?? "" },
  embeddingConfigId: { key: "embedding_config_id", to: (v) => (v as string) ?? "" },
  synthesisConfigId: { key: "synthesis_config_id", to: (v) => (v as string) ?? "" },
  compactionConfigId: { key: "compaction_config_id", to: (v) => (v as string) ?? "" },
  titleConfigId: { key: "title_config_id", to: (v) => (v as string) ?? "" },
  routerConfigId: { key: "router_config_id", to: (v) => (v as string) ?? "" },
  visionConfigId: { key: "vision_config_id", to: (v) => (v as string) ?? "" },
  curationEnabled: { key: "curation_enabled", to: (v) => (v as boolean) ?? false },
  evolutionAuto: { key: "evolution_auto", to: (v) => (v ? "on" : "off") },
  evolutionMaxDispatches: { key: "evolution_max_dispatches", to: (v) => (v as number) ?? null },
  ocrLanguages: { key: "ocr_languages", to: (v) => (v as string) ?? "" },
  runDebugRetentionDays: { key: "run_debug_retention_days", to: (v) => (v as number) ?? 30 },
  mcpServerEnabled: { key: "mcp_server_enabled" },
};

/** The two secrets. Sent only when the value is real — never a mask echoed back. */
const SECRET_WIRE: Record<string, keyof BackendAppSettings> = {
  apiKeySearch: "search_api_key",
  githubToken: "github_token",
};

/**
 * The body for a save that touched exactly these fields.
 *
 * 🔴 THE POINT: a PUT must not write back a field the user never edited. Three
 * separate bugs came from doing so, each fixed per field:
 *   ① a masked key round-tripped as the real secret;
 *   ② llm_strategy clobbered by a client default that was never hydrated;
 *   ③ search_provider="tavily" on a fresh install, which broke keyless search
 *      the moment the user changed anything at all.
 * Per-field fixes kill the instance and leave the family. Sending only what was
 * touched removes the shape. The backend does `model_dump(exclude_none=True)`, so
 * an omitted field is simply not written.
 */
export function toBackendSettingsPatch(patch: Partial<AppSettings>): Partial<BackendAppSettings> {
  const body: Record<string, unknown> = {};
  for (const [uiName, value] of Object.entries(patch)) {
    const wire = SETTINGS_WIRE[uiName];
    if (wire) {
      body[wire.key as string] = wire.to ? wire.to(value) : value;
      continue;
    }
    const secret = SECRET_WIRE[uiName];
    // A key field can be in the patch because the user focused and blurred it
    // without typing, and what it holds then is the mask it was shown.
    if (secret && typeof value === "string" && value && !looksMasked(value)) {
      body[secret as string] = value;
    }
  }
  return body as Partial<BackendAppSettings>;
}

/**
 * The whole-settings body. Built from the same table as the patch adapter so the
 * two cannot describe a field differently.
 *
 * Prefer `toBackendSettingsPatch` for saves: this one writes back every field,
 * including ones the user never touched, which is the defect family described
 * above. Kept for the paths that genuinely mean "persist all of it".
 */
export function toBackendSettings(ui: AppSettings): Partial<BackendAppSettings> {
  const everything: Partial<AppSettings> = {};
  for (const uiName of [...Object.keys(SETTINGS_WIRE), ...Object.keys(SECRET_WIRE)]) {
    (everything as Record<string, unknown>)[uiName] = (ui as unknown as Record<string, unknown>)[uiName];
  }
  return toBackendSettingsPatch(everything);
}

// ── Spawn adapters ────────────────────────────────────────────────────────────

/**
 * Maps a backend SpawnSummary DTO to the UI Spawn shape used by AI Studio components.
 *
 * Key mappings:
 * - id: number  →  id: string (String(id))
 * - total_tasks: number  →  totalTasks: number
 * - capabilities: string[]  →  tools/skills (passthrough as tools; skills empty unless provided)
 * - status: backend has no status field, default to "idle"
 * - avatarEmoji: default "🤖"
 */
export function toUiSpawn(s: SpawnSummary & {
  status?: string;
  tools?: string[];
  skills?: string[];
  total_tasks?: number;
  description?: string;
}): Spawn {
  return {
    id: String(s.id),
    name: s.name,
    domain: s.domain ?? "",
    description: s.description ?? "",
    status: (s.status as Spawn["status"]) ?? "idle",
    avatarEmoji: "🤖",
    tools: s.tools ?? s.capabilities ?? [],
    skills: s.skills ?? [],
    totalTasks: s.total_tasks ?? 0,
    hasActiveChat: s.has_active_chat ?? false,
  };
}

// ── Arslan thread adapters ────────────────────────────────────────────────────

/**
 * Maps an ArslanThreadItem[] (from arslanStore) → Message[] (AI Studio UI type).
 *
 * Field mapping per kind:
 *
 * kind === "message", role === "user"
 *   sender: "user", senderName: "You", senderAvatar: "🦁"
 *   text: content
 *
 * kind === "message", role === "arslan"
 *   sender: "arslan", senderName: "Arslan", senderAvatar: "🦁"
 *   text: content
 *   routedTo: undefined (routing is a separate item kind, not folded here)
 *
 * kind === "message", role === "spawn"
 *   sender: "spawn", senderName: spawnName ?? "Spawn", senderAvatar: "🤖"
 *   text: content
 *   toolActivity: first ToolStep mapped if present (folded into the reply)
 *
 * kind === "escalation"
 *   sender: "spawn", senderName: spawnName ?? "Spawn", senderAvatar: "🤖"
 *   text: "" (the escalation card is the content)
 *   escalation: mapped from item.escalation (EscalationInfo → UI Escalation)
 *
 * kind === "system" (spawn_created)
 *   sender: "arslan", senderName: "Arslan", senderAvatar: "🦁"
 *   text: content (the "__SPAWN_CREATED__:Name" sentinel or intro)
 *   spawnIntro: populated from equipment + intro if available
 *
 * kind === "fact"
 *   sender: "arslan", senderName: "Arslan", senderAvatar: "🦁"
 *   text: content
 *
 * Fields with no counterpart (routedTo for routing items, timestamp) get
 * sensible defaults: timestamp = "" (component shows it conditionally).
 */
export function toUiMessages(items: ArslanThreadItem[]): Message[] {
  return items.map((item): Message => {
    const id = String(item.id);
    const timestamp = "";

    if (item.kind === "escalation" && item.escalation) {
      const esc = item.escalation;
      // Map EscalationInfo.status → UI Escalation.status
      const uiStatus =
        esc.status === "resolving" ? ("arslan_resolving" as const)
        : esc.status === "resolved" ? ("resolved" as const)
        : esc.status === "refused"  ? ("refused" as const)
        : ("need_raised" as const);
      return {
        id,
        sender: "spawn",
        senderName: esc.spawnName ?? "Spawn",
        senderAvatar: "🤖",
        text: "",
        timestamp,
        escalation: {
          id,
          spawnName: esc.spawnName ?? "Spawn",
          issue: esc.need,
          status: uiStatus,
          resolutionMessage: esc.how ?? esc.why,
        },
      };
    }

    if (item.kind === "system") {
      // Routing brief: need restatement + @-mention duty lines (mention chips in UI).
      if (item.isRouteAnnouncement) {
        return {
          id,
          sender: "arslan",
          senderName: "Arslan",
          senderAvatar: "🦁",
          text: item.content,
          timestamp,
          isRouteAnnouncement: true,
        };
      }
      // Roster notice: rosterAction is "joined" | "left" | "recruited" | "joined_no_pending"
      if (item.rosterAction) {
        return {
          id,
          sender: "arslan",
          senderName: "Arslan",
          senderAvatar: "🦁",
          text: "",
          timestamp,
          rosterAction: item.rosterAction,
          rosterSpawnName: item.spawnName ?? null,
        };
      }
      // spawn_updated (P2): render a readable notice + the fresh equipment chips.
      if (item.content.startsWith("__SPAWN_UPDATED__:")) {
        const updatedName = item.content.slice("__SPAWN_UPDATED__:".length);
        return {
          id,
          sender: "arslan",
          senderName: "Arslan",
          senderAvatar: "🦁",
          // Sentinel kept — App translates it (adapters must stay i18n-free:
          // importing the i18n singleton breaks every test that mocks react-i18next).
          text: item.content,
          timestamp,
          spawnIntro: item.equipment
            ? {
                name: updatedName,
                domain: "",
                avatarEmoji: "🤖",
                tools: item.equipment.toolsets.map((x) => x.key),
                skills: item.equipment.skills.map((x) => x.key),
              }
            : undefined,
        };
      }
      // spawn_created: content is "__SPAWN_CREATED__:Name" or intro text
      const spawnNameFromContent = item.content.startsWith("__SPAWN_CREATED__:")
        ? item.content.slice("__SPAWN_CREATED__:".length)
        : null;
      const spawnIntro = spawnNameFromContent
        ? {
            name: spawnNameFromContent,
            domain: "",
            avatarEmoji: "🤖",
            tools: item.equipment?.toolsets.map((t) => t.key) ?? [],
            skills: item.equipment?.skills.map((s) => s.key) ?? [],
          }
        : undefined;
      return {
        id,
        sender: "arslan",
        senderName: "Arslan",
        senderAvatar: "🦁",
        text: item.intro ?? item.content,
        timestamp,
        spawnIntro,
      };
    }

    if (item.kind === "fact") {
      return {
        id,
        sender: "arslan",
        senderName: "Arslan",
        senderAvatar: "🦁",
        text: item.content,
        timestamp,
      };
    }

    // kind === "message"
    if (item.role === "user") {
      return {
        id,
        sender: "user",
        senderName: "You",
        senderAvatar: "🦁",
        text: item.content,
        timestamp,
        // Session-only attachment echo (image thumbnails / doc chips in the sent bubble).
        attachments: item.attachments,
      };
    }

    if (item.role === "spawn") {
      // Map the first ToolStep to a ToolActivity if present
      const firstStep = item.toolSteps?.[0];
      const toolActivity: Message["toolActivity"] = firstStep
        ? {
            id: `${id}-tool-0`,
            toolName: firstStep.tool,
            emoji: "🔧",
            status: firstStep.status === "running" ? "running" : "completed",
            // Raw status (incl. error) so the tool card can show ✓/✗ honestly.
            stepStatus: firstStep.status,
            action: firstStep.argsSummary,
            outputSummary: firstStep.resultSummary ?? "",
            collapsed: false,
            // 🔒 SECURITY: backend render_chart artifact only (set in arslanStore
            // from the tool_result frame), NEVER from LLM message text.
            // Surface the artifact from whichever step produced one (a chart is often
            // not the first tool, e.g. search-then-chart), not just toolSteps[0].
            artifactSvg: item.toolSteps?.find((s) => s.artifactSvg)?.artifactSvg,
            artifactChart: item.toolSteps?.find((s) => s.artifactChart)?.artifactChart,
            // pptx was missed here when charts were wired — without it the deck's
            // download card never rendered on the orchestrator thread even though
            // the file was generated and sitting in the store (live incident).
            artifactPptx: item.toolSteps?.find((s) => s.artifactPptx)?.artifactPptx,
          }
        : undefined;
      return {
        id,
        sender: "spawn",
        senderName: item.spawnName ?? "Spawn",
        senderAvatar: "🤖",
        text: item.content,
        timestamp,
        toolActivity,
        // 🔒 HTML deliverable card — set in arslanStore from the stream_end frame's
        // kind:"html" artifact (HX-2 channel), NEVER from LLM message text.
        artifactHtml: item.artifactHtml,
        // Pass through staged orchestration fields
        spawnId: item.spawnId != null ? String(item.spawnId) : undefined,
        isProposal: item.isProposal ?? undefined,
        messageId: item.spawnMessageId ?? undefined,
        taskBrief: item.taskBrief ?? undefined,
        runId: item.runId ?? undefined,
        refinedFrom: item.refinedFrom ?? undefined,
        // S3-M1: partial output of a cancelled run → interrupted marker in the bubble.
        cancelled: item.cancelled ?? undefined,
        // S3-M3: the turn's usage from the stream_end frame → bubble usage chip.
        usage: item.usage,
      };
    }

    // role === "arslan" (default)
    return {
      id,
      sender: "arslan",
      senderName: "Arslan",
      senderAvatar: "🦁",
      text: item.content,
      timestamp,
      // 🔒 stream_end html artifact can also ride an arslan-role turn (escalation path).
      artifactHtml: item.artifactHtml,
      // PA-3 structured clarification card (🔒 backend clarify_options frames only).
      clarifyOptions: item.clarifyOptions,
      // S3-M1: run_cancelled can also finalize an arslan-role live bubble.
      cancelled: item.cancelled ?? undefined,
      // S3-M3: answer-turn usage from the stream_end frame → bubble usage chip.
      usage: item.usage,
    };
  });
}

// ── Run trace+eval adapters ───────────────────────────────────────────────────

// Caller-provided translate function (react-i18next `t`). Adapters must stay
// i18n-free at module scope — importing the i18n singleton breaks every test
// that mocks react-i18next — so `t` is threaded in from the rendering component
// (same precedent as RunReplay's buildRunMarkdown(run, t)).
export type TranslateFn = (key: string, opts?: Record<string, unknown>) => string;

const TOOL_LABEL_KEYS: Record<string, string> = {
  web_search: "replay.tool_web_search",
  fetch_url: "replay.tool_fetch_url",
  read_file: "replay.tool_read_file",
};

// Professional-but-plain wording (user asked: 专业的人话, not colloquial).
// Locale KEYS — consumers (EvalSummary charts, RunReplay radar) translate with
// their own `t` so every chart uses the exact same labels.
export const DIMENSION_LABEL_KEYS: Record<string, string> = {
  routing: "replay.dim_routing",
  fabrication: "replay.dim_fabrication",
  identity: "replay.dim_identity",
  completion: "replay.dim_completion",
};

function stepLabel(step: RunStepDto, t: TranslateFn): string {
  const spawn = (step.ref.spawn_name as string) ?? "";
  switch (step.kind) {
    case "route":
      return t("replay.step_route", { spawn }).trim();
    case "dispatch":
      return t("replay.step_dispatch", { spawn }).trim();
    case "tool_call": {
      const tool = (step.ref.tool as string) ?? "";
      return TOOL_LABEL_KEYS[tool] ? t(TOOL_LABEL_KEYS[tool]) : t("replay.step_tool", { tool }).trim();
    }
    case "escalation":
      return t("replay.step_escalation", { need: (step.ref.need as string) ?? "" }).trim();
    default:
      return step.kind;
  }
}

export function toUiRun(dto: RunDetailDto, t: TranslateFn): UiRun {
  const { run, steps, evaluations } = dto;
  const maxMs = steps.reduce((m, s) => Math.max(m, s.duration_ms ?? 0), 0);
  const uiSteps: UiRunStep[] = steps.map((s) => ({
    seq: s.seq,
    kind: s.kind,
    label: stepLabel(s, t),
    detail: s.detail,
    ok: typeof s.ref.ok === "boolean" ? s.ref.ok : undefined,
    durationMs: s.duration_ms,
    isSlowest: maxMs > 0 && (s.duration_ms ?? 0) === maxMs,
    argsFull: typeof s.detail?.args_full === "string" ? s.detail.args_full : undefined,
    resultRaw: typeof s.detail?.result_raw === "string" ? s.detail.result_raw : undefined,
    error: typeof s.detail?.error === "string" ? s.detail.error : undefined,
  }));
  const dimensions: UiRunDimension[] = evaluations.map((e) => ({
    dimension: e.dimension,
    label: DIMENSION_LABEL_KEYS[e.dimension] ? t(DIMENSION_LABEL_KEYS[e.dimension]) : e.dimension,
    status: (["pass", "warn", "fail"].includes(e.status) ? e.status : "warn") as UiRunDimension["status"],
    score: e.score,
    comment: e.comment,
  }));
  return {
    id: run.id,
    spawnName: run.spawn_name,
    userMessage: run.user_message,
    status: run.status,
    totalMs: run.total_ms,
    taskTokens: run.task_tokens,
    overallScore: run.overall_score,
    overallBadge: run.overall_badge,
    steps: uiSteps,
    dimensions,
    scored: run.status === "scored",
    model: run.model ?? undefined,
    provider: run.provider ?? undefined,
    tokensIn: run.tokens_in ?? undefined,
    tokensOut: run.tokens_out ?? undefined,
    tokensEstimated: run.tokens_estimated,
    errorKind: run.error_kind ?? undefined,
    errorText: run.error_text ?? undefined,
    systemPrompt: run.system_prompt ?? undefined,
    injectedKb: run.injected_kb ?? undefined,
    injectedKbSources: run.injected_kb_sources ?? undefined,
    spawnId: run.spawn_id,
    finalOutput: run.final_output ?? undefined,
  };
}
