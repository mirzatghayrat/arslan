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
    embeddingConfigId: backend.embedding_config_id ?? "",
    evolutionAuto: backend.evolution_auto === "on",
    evolutionMaxDispatches: backend.evolution_max_dispatches ?? null,
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
export function toBackendSettings(ui: AppSettings): Partial<BackendAppSettings> {
  const body: Partial<BackendAppSettings> = {
    search_provider: ui.searchProvider,
    language: ui.language,
    llm_strategy: ui.llmStrategy,
    distill_on_session_end: ui.distillOnSessionEnd,
    orchestrator_shell_enabled: ui.orchestratorShellEnabled ? "true" : "false",
    shell_confirm_policy: ui.shellConfirmPolicy,
    embedding_config_id: ui.embeddingConfigId ?? "",
    evolution_auto: ui.evolutionAuto ? "on" : "off",
    evolution_max_dispatches: ui.evolutionMaxDispatches ?? null,
    run_debug_retention_days: ui.runDebugRetentionDays ?? 30,
    mcp_server_enabled: ui.mcpServerEnabled,
  };

  // Only send the search key if the user entered something new (non-empty, non-masked).
  if (ui.apiKeySearch && !looksMasked(ui.apiKeySearch)) {
    body.search_api_key = ui.apiKeySearch;
  }

  // Same mask-aware round-trip for the GitHub token secret.
  if (ui.githubToken && !looksMasked(ui.githubToken)) {
    body.github_token = ui.githubToken;
  }

  return body;
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

const TOOL_LABELS: Record<string, string> = {
  web_search: "查资料",
  fetch_url: "读网页",
  read_file: "读文件",
};

// Professional-but-plain wording (user asked: 专业的人话, not colloquial).
// Exported so EvalSummary's charts use the exact same labels.
export const DIMENSION_LABELS: Record<string, string> = {
  routing: "路由匹配",
  fabrication: "事实可靠",
  identity: "角色一致",
  completion: "任务完成度",
};

function stepLabel(step: RunStepDto): string {
  const spawn = (step.ref.spawn_name as string) ?? "";
  switch (step.kind) {
    case "route":
      return `选了 ${spawn}`.trim();
    case "dispatch":
      return `交给 ${spawn} 处理`.trim();
    case "tool_call": {
      const tool = (step.ref.tool as string) ?? "";
      return TOOL_LABELS[tool] ?? `用工具 ${tool}`.trim();
    }
    case "escalation":
      return `求助：${(step.ref.need as string) ?? ""}`.trim();
    default:
      return step.kind;
  }
}

export function toUiRun(dto: RunDetailDto): UiRun {
  const { run, steps, evaluations } = dto;
  const maxMs = steps.reduce((m, s) => Math.max(m, s.duration_ms ?? 0), 0);
  const uiSteps: UiRunStep[] = steps.map((s) => ({
    seq: s.seq,
    kind: s.kind,
    label: stepLabel(s),
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
    label: DIMENSION_LABELS[e.dimension] ?? e.dimension,
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
