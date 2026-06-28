import type { AppSettings, Message, Spawn, UiRun, UiRunDimension, UiRunStep } from "../types";
import type { AppSettings as BackendAppSettings, ArslanThreadItem, RunDetailDto, RunStepDto, SpawnSummary } from "./client.types";

// ── Settings adapters ─────────────────────────────────────────────────────────

// Backend masked value sentinel (the server returns this literal when a key is set but masked).
const MASKED_SENTINEL_RE = /^[•*]+$/;

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
 * UI-only fields with no backend counterpart are kept at their current UI value
 * and therefore should NOT be overwritten on fetch; callers must merge:
 *   theme, telemetry, spawnMode
 */
export function toUiSettings(backend: BackendAppSettings): Omit<AppSettings, "theme" | "telemetry" | "spawnMode" | "llmStrategy"> {
  return {
    searchProvider: backend.search_provider ?? "",
    apiKeySearch: backend.search_api_key ?? "",
    githubToken: backend.github_token ?? "",
    language: backend.language ?? "en",
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
  };

  // Only send the search key if the user entered something new (non-empty, non-masked).
  if (ui.apiKeySearch && !MASKED_SENTINEL_RE.test(ui.apiKeySearch)) {
    body.search_api_key = ui.apiKeySearch;
  }

  // Same mask-aware round-trip for the GitHub token secret.
  if (ui.githubToken && !MASKED_SENTINEL_RE.test(ui.githubToken)) {
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
      // Roster notice: rosterAction is "joined" | "left"
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
            action: firstStep.argsSummary,
            outputSummary: firstStep.resultSummary ?? "",
            collapsed: false,
            // 🔒 SECURITY: backend render_chart artifact only (set in arslanStore
            // from the tool_result frame), NEVER from LLM message text.
            // Surface the artifact from whichever step produced one (a chart is often
            // not the first tool, e.g. search-then-chart), not just toolSteps[0].
            artifactSvg: item.toolSteps?.find((s) => s.artifactSvg)?.artifactSvg,
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
        // Pass through staged orchestration fields
        spawnId: item.spawnId != null ? String(item.spawnId) : undefined,
        isProposal: item.isProposal ?? undefined,
        messageId: item.spawnMessageId ?? undefined,
        taskBrief: item.taskBrief ?? undefined,
        runId: item.runId ?? undefined,
        refinedFrom: item.refinedFrom ?? undefined,
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
    };
  });
}

// ── Run trace+eval adapters ───────────────────────────────────────────────────

const TOOL_LABELS: Record<string, string> = {
  web_search: "查资料",
  fetch_url: "读网页",
  read_file: "读文件",
};

const DIMENSION_LABELS: Record<string, string> = {
  routing: "选对了人",
  fabrication: "没有编造",
  identity: "没串错身份",
  completion: "完成度",
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
    durationMs: s.duration_ms,
    isSlowest: maxMs > 0 && (s.duration_ms ?? 0) === maxMs,
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
  };
}
