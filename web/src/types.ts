export interface ToolActivity {
  id: string;
  toolName: string;
  emoji: string;
  status: 'running' | 'completed';
  /** Raw first-step status incl. error ('running' | 'ok' | 'error') — drives the ✓/✗ on the tool card. */
  stepStatus?: 'running' | 'ok' | 'error';
  action: string;
  outputSummary: string;
  collapsed: boolean;
  /** SVG markup from a backend render_chart tool_result artifact. NEVER from LLM message text. */
  artifactSvg?: string;
  /** ECharts option object from a backend render_chart tool_result artifact (kind: "echarts"). NEVER from LLM message text. */
  artifactChart?: Record<string, unknown>;
  /** Downloadable .pptx from a backend render_deck tool_result artifact (kind: "pptx"). NEVER from LLM message text. */
  artifactPptx?: { filename: string; bytesB64: string; slides: number };
}

/** HTML deliverable from the backend stream_end frame's artifact (kind: "html", HX-2 channel).
 *  `content` is the full document text (sandboxed-iframe preview + blob download);
 *  `complete=false` marks a max-tokens-truncated doc (「⚠ 输出被截断」 badge).
 *  🔒 Populated ONLY from backend frames, NEVER from LLM message text. */
export interface HtmlArtifact {
  title: string;
  filename: string;
  content: string;
  complete: boolean;
  bytes: number;
}

export interface Escalation {
  id: string;
  spawnName: string;
  issue: string;
  status: 'need_raised' | 'arslan_resolving' | 'resolved' | 'refused';
  resolutionMessage?: string;
}

/** Display info for an attachment echoed inside a SENT user bubble.
 *  previewUrl is a session-only object-URL (never persisted); when it is absent —
 *  e.g. a history-restored message — the UI falls back to a compact file chip. */
export interface MessageAttachment {
  name: string;
  kind?: 'doc' | 'image';
  previewUrl?: string;
}

export interface Message {
  id: string;
  sender: 'user' | 'arslan' | 'spawn';
  senderName: string;
  senderAvatar: string;
  text: string;
  timestamp: string;
  /** Attachments sent with this user message (session-only display echo; see MessageAttachment). */
  attachments?: MessageAttachment[];
  spawnId?: string;
  /** True when this spawn deliverable is a pending proposal needing direction confirmation. */
  isProposal?: boolean;
  /** Set after verdict_recorded ack: 'accept' | 'discard' | 'redo' */
  verdict?: string;
  /** Backend message id for verdict frames (spawnMessageId from the store item). */
  messageId?: number;
  /** Run id for the trace+eval replay of this spawn deliverable. */
  runId?: number | null;
  /** The task brief this spawn turn ran — used to re-dispatch the same task on redo. */
  taskBrief?: string | null;
  /** The spawn's display name for this deliverable — used to seed the refine side chat. */
  spawnName?: string;
  /** Original deliverable message id this was refined from (deliverable_finalized) — drives the 定稿 badge. */
  refinedFrom?: number | null;
  /** S3-M1: true when this bubble is the partial output of a run the user cancelled
   *  mid-stream — renders the muted interrupted marker under the body. */
  cancelled?: boolean;
  /** S3-M3: the turn's usage (from the stream_end frame) — renders the small
   *  muted usage chip under the bubble body. */
  usage?: {
    tokens_in: number | null;
    tokens_out: number | null;
    tokens_total: number;
    estimated: boolean;
    usd: number | null;
  };
  routedTo?: {
    spawnId: string;
    spawnName: string;
  };
  /** Routing brief (need + @-mention duty lines) — rendered with mention chips. */
  isRouteAnnouncement?: boolean;
  /** Roster notice: "joined" | "left" | "recruited" | "joined_no_pending" — present on
   *  system messages from roster_event frames (see server/ws/protocol.py::roster_event). */
  rosterAction?: string;
  /** The spawn name for a roster notice item. */
  rosterSpawnName?: string | null;
  spawnIntro?: {
    name: string;
    domain: string;
    avatarEmoji: string;
    tools: string[];
    skills: string[];
  };
  toolActivity?: ToolActivity;
  /** HTML deliverable card data (kind:"html" stream_end artifact). 🔒 Backend frames only. */
  artifactHtml?: HtmlArtifact;
  escalation?: Escalation;
  /** PA-3 structured clarification card: question + 2-4 one-click options.
   *  🔒 Backend clarify_options frames only — never parsed from LLM message text. */
  clarifyOptions?: { question: string; options: { label: string; hint?: string }[]; answered?: boolean };
}

export interface Spawn {
  id: string;
  name: string;
  domain: string;
  description: string;
  status: 'idle' | 'working' | 'escalated';
  avatarEmoji: string;
  tools: string[]; // List of Tool IDs
  skills: string[]; // List of Skill IDs
  totalTasks: number;
  hasActiveChat?: boolean;
}

export interface UiRunStep {
  seq: number;
  kind: string;
  label: string;
  detail?: Record<string, unknown>;
  /** From ref.ok — tool success/failure (undefined when the step has no ok flag, e.g. route/dispatch). */
  ok?: boolean;
  durationMs: number | null;
  isSlowest: boolean;
  /** Full (untruncated-at-summary-level) tool args JSON — from detail.args_full. Absent once redacted. */
  argsFull?: string;
  /** Raw tool result text (may be truncated server-side) — from detail.result_raw. Absent once redacted. */
  resultRaw?: string;
  /** Tool-level error message — from detail.error. */
  error?: string;
}

export interface UiRunDimension {
  dimension: string;
  label: string;
  status: 'pass' | 'warn' | 'fail';
  score: number;
  comment: string;
}

export interface UiRun {
  id: number;
  spawnName: string | null;
  userMessage: string;
  status: string;
  totalMs: number | null;
  taskTokens: number;
  overallScore: number | null;
  overallBadge: string | null;
  steps: UiRunStep[];
  dimensions: UiRunDimension[];
  scored: boolean;
  /** Model the spawn actually used for this run (null when unknown/pre-P2/redacted). */
  model?: string | null;
  /** Provider key (openai|anthropic|gemini|zhipu…). */
  provider?: string | null;
  /** Real provider input tokens, when a non-stream call reported them. */
  tokensIn?: number | null;
  /** Real provider output tokens. */
  tokensOut?: number | null;
  /** True when taskTokens is an estimate (the common case — spawns stream). */
  tokensEstimated?: boolean;
  /** Structured error class/category, when the run failed. */
  errorKind?: string | null;
  /** Error message (truncated), when the run failed. */
  errorText?: string | null;
  /** SENSITIVE: assembled system prompt — retention-governed, null once redacted. */
  systemPrompt?: string | null;
  /** SENSITIVE: injected knowledge — retention-governed, null once redacted. */
  injectedKb?: string | null;
  /** Structured knowledge source labels injected into this run's prompt — retention-governed, null/empty once redacted. */
  injectedKbSources?: string[];
  /** The spawn this run belongs to (for the history sparkline). Null for orchestrator-level runs. */
  spawnId?: number | null;
  /** Full deliverable text (M4 I-1) — present for scheduled/replay runs whose
   * conversation is unreachable from the sidebar; absent for plain live runs. */
  finalOutput?: string | null;
}

export interface AppSettings {
  searchProvider: string;
  /** Self-hosted SearXNG address. Plain text — an address, not a credential. */
  searchBaseUrl: string;
  apiKeySearch: string;
  githubToken: string;
  language: string;
  theme: 'dark' | 'light';
  telemetry: boolean;
  spawnMode: 'auto' | 'interactive' | 'strict';
  llmStrategy: 'single' | 'cost' | 'balanced' | 'performance';
  distillOnSessionEnd: boolean;
  /** Orchestrator (Arslan) may run whitelisted shell commands. Off by default. */
  orchestratorShellEnabled: boolean;
  /** Confirmation posture for shell commands. */
  shellConfirmPolicy: 'ask_all' | 'ask_risky';
  /** Embedding provider override: "" = auto, "local" = local model, or a provider-config id (as string). */
  embeddingConfigId?: string;
  /** Days a run's sensitive/bulky debug detail is kept before the boot sweep redacts it. Default 30. */
  runDebugRetentionDays?: number;
  /** S4.1-C: whether the inbound MCP server (exposing Arslan's read-only tools
   *  to external MCP clients like Claude Code/Codex) is enabled. Default off. */
  mcpServerEnabled: boolean;
  /** Sleep-time curation sweep. Optional on purpose, like evolutionAuto: it
   *  keeps existing AppSettings literals valid. Default off — it spends, and
   *  until this round it had NO UI at all, only a server field. */
  curationEnabled?: boolean;
  /** optional on purpose: keeps existing AppSettings literals valid */
  evolutionAuto?: boolean;
  /** Cap on PROJECTED replay dispatches. null/undefined = no cap (the default). */
  evolutionMaxDispatches?: number | null;
  /** Comma-separated BCP-47 tags for image text recognition. Empty/unset means
   *  "follow the interface language, plus English". Deliberately a SHORT list:
   *  recognition degrades as the request widens and CJK is lost first. */
  ocrLanguages?: string;
}
