import type { HtmlArtifact, MessageAttachment } from "../types";

export interface EquipmentItem {
  key: string;
  name: string;
  status: string;
  grant: "permanent" | "temporary";
  granted_by?: "create" | "user" | "escalation";
  expires_turn?: number | null;
}

export interface Equipment {
  toolsets: EquipmentItem[];
  skills: EquipmentItem[];
}

export interface RegistryTool { key: string; description: string; tier: string; status: string; }
export interface RegistryToolset {
  key: string; name: string; description: string; tier: string; status: string;
  assignable: boolean; tools: RegistryTool[];
  /** P0-1 决定①b: run-time degradation (e.g. run_python running UNSANDBOXED via the escape
   * valve). When true, the capability page badges the toolset with `warning`. */
  degraded?: boolean; warning?: string | null;
}
export interface RegistrySkill {
  key: string; name: string; category: string; description: string;
  tier: string; status: string; assignable: boolean;
  /** PC-4: honest sandbox-compatibility class — "full" | "partial" | "text". */
  compatibility?: "full" | "partial" | "text";
}
export interface RegistryCatalog { toolsets: RegistryToolset[]; skills: RegistrySkill[]; }

/** PC-5 per-skill health report (POST /registry/skills/{key}/health). Mirrors the PB-4
 * MCP health shape: a structured storage/scripts/references breakdown + an honest roll-up.
 * `sandbox_available` is the read-only backend probe — a script is never "runnable" when
 * it is false. */
export interface SkillHealth {
  key: string;
  status: "ok" | "degraded";
  ok: boolean;
  sandbox_available: boolean;
  sandbox_backend: string;
  compatibility?: "full" | "partial" | "text";
  storage: {
    ok: boolean;
    body_present: boolean;
    declared_scripts: string[];
    declared_references: string[];
    disk_scripts: string[];
    disk_references: string[];
    missing: string[];
    orphaned: string[];
  };
  scripts: Array<{ name: string; runnable: boolean; reason: string }>;
  references: Array<{ name: string; readable: boolean; reason: string }>;
  timed_out?: boolean;
  error?: string;
}

/** One step of a spawn's tool loop, paired from tool_call/tool_result frames. */
export interface ToolStep {
  tool: string;
  argsSummary: string;
  status: "running" | "ok" | "error";
  resultSummary?: string;
  /** SVG markup from a backend render_chart tool_result artifact. NEVER from LLM message text. */
  artifactSvg?: string;
  /** ECharts option object from a backend render_chart tool_result artifact (kind: "echarts"). NEVER from LLM message text. */
  artifactChart?: Record<string, unknown>;
  /** Downloadable .pptx from a backend render_deck tool_result artifact (kind: "pptx"). NEVER from LLM message text. */
  artifactPptx?: { filename: string; bytesB64: string; slides: number };
}

export interface EscalationInfo {
  spawnId: number;
  spawnName: string | null;
  kind: string; // "data" | "capability"
  need: string;
  status: "resolving" | "resolved" | "refused";
  how?: string;
  detail?: string;
  why?: string;
}

export interface SpawnSummary {
  id: number;
  name: string;
  domain: string;
  capabilities: string[];
  template_used: string | null;
  generation_level: number;
  created_at: string;
  updated_at: string;
  equipment?: Equipment;
  has_active_chat?: boolean;
  /** Built-in agent shipped with the app — cannot be deleted. */
  is_default?: boolean;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  timestamp?: string;
}

/** A persona "seed identity" reference (one of the 249), resolved for display. */
export interface SeedRef {
  slug: string;
  name: string;
  division: string;
  summary: string;
}

export interface SeedsResponse {
  seeds: SeedRef[];
  total: number;
}

export interface SpawnDetail extends SpawnSummary {
  persona_role: string | null;
  persona_tone: string | null;
  system_prompt: string;
  messages: ChatMessage[];
  /** The composed persona seed identities (resolved). */
  seeds?: SeedRef[];
}

export interface AppSettings {
  llm_provider: string;
  llm_model: string;
  llm_base_url: string;
  llm_api_key: string; // masked on read
  language: string;
  search_provider: string;
  search_api_key: string; // masked on read
  github_token: string; // masked on read
  llm_strategy?: string;
  distill_on_session_end?: boolean;
  orchestrator_shell_enabled?: string; // "true" | "false"
  shell_confirm_policy?: string; // "ask_all" | "ask_risky"
  /** Embedding provider override: "" (or absent) = auto, "local", or a provider-config id. */
  embedding_config_id?: string;
  /** Days a run's sensitive/bulky debug detail is kept before the boot sweep redacts it. Default 30. */
  run_debug_retention_days?: number;
}

export interface ProviderOption {
  key: string;
  label: string;
  base_url: string;
  default_model: string;
  native: boolean;
  models: string[];
}

/** GET /settings/access-token — whether the server gates on a bearer token, and
 *  (only when the caller is localhost) the bootstrapped token itself so the local
 *  operator can see/copy it. `token` is null for non-localhost callers. */
export interface AccessTokenInfo {
  token_required: boolean;
  token: string | null;
}

export interface ProviderConfig {
  id: number;
  label: string;
  provider: string;
  model: string;
  base_url: string;
  api_key: string;     // masked on read
  is_primary: boolean;
}

export interface TemplateInfo {
  name: string;
  domain: string;
  description: string;
  tags: string[];
}

export interface EvolutionRule {
  rule_type: string;
  rule: string;
  confidence: number;
  sample_size: number;
}

export interface EvolutionStats {
  feedback_count: number;
  active_rules: EvolutionRule[];
}

// WebSocket wire messages (server -> client)
export type ServerMessage =
  | { type: "question"; node_id: string; text: string; options: string[] | null; multi_select: boolean; hint: string }
  | { type: "progress"; step: number; total: number; node_id: string }
  | { type: "build_complete"; spawn_id: number; spawn_name: string }
  | { type: "history"; messages: { message_id: number; role: string; content: string }[] }
  | { type: "stream_start"; message_id: number }
  | { type: "stream_chunk"; content: string }
  | { type: "stream_end"; message_id: number }
  | { type: "message"; message_id: number; content: string; role: string }
  | { type: "error"; code: string; message: string; recoverable?: boolean }
  | { type: "ping"; ts: number };

export interface UserFact {
  id: number;
  content: string;
  source: "auto" | "manual";
  sensitive: boolean;
  category?: string | null;
  label?: string | null;
}

export interface SuggestDraft {
  name: string;
  domain: string;
  capabilities: string[];
  persona_role?: string | null;
  persona_tone?: string | null;
  reason?: string | null;
  tools?: string[];
  skills?: string[];
  mcps?: string[];
  gaps?: string[];
  seed_refs?: string[];
  task_brief?: string | null;
}

export interface OverlapInfo {
  spawn_id: number;
  name: string;
  axes: string[];
}

/** Proposed changes to an existing spawn (from a `suggest_update` frame; wire snake_case). */
export interface SpawnUpdateChanges {
  persona_role?: string;
  persona_tone?: string;
  capabilities?: string[];
  add_toolsets?: string[];
  remove_toolsets?: string[];
  add_skills?: string[];
  remove_skills?: string[];
}

/** The spawn's config at proposal time (before side of the suggest_update card). */
export interface SpawnUpdateCurrent {
  persona_role: string;
  persona_tone: string;
  capabilities: string[];
  toolsets: string[];
  skills: string[];
}

/** One candidate from a `propose_staffing` frame (wire shape: snake_case). */
export interface StaffingCandidate {
  spawn_id: number;
  name: string | null;
  score: number;
  why: string;
}

/** One option of a `clarify_options` frame (PA-3 structured clarification card). */
export interface ClarifyOption {
  label: string;
  hint?: string;
}

/** A renderable item in the unified Arslan thread. */
export interface ArslanThreadItem {
  id: number;
  kind: "message" | "fact" | "system" | "escalation";
  role: "user" | "arslan" | "spawn";
  content: string;
  spawnId?: number | null;
  spawnName?: string | null;
  sensitive?: boolean; // kind === "fact"
  spawnMessageId?: number | null; // chat_messages assistant id, for feedback/redo/refine
  runId?: number | null; // trace+eval replay id, from spawn_meta
  taskBrief?: string | null; // the task this spawn turn ran, for redo/refine
  equipment?: Equipment | null; // kind === "system" (spawn_created)
  intro?: string | null; // kind === "system" (spawn_created)
  toolSteps?: ToolStep[]; // spawn replies: folded tool activity
  /** HTML deliverable from the stream_end frame's kind:"html" artifact (HX-2 channel).
   *  🔒 Populated ONLY from the backend frame, NEVER from LLM message text. */
  artifactHtml?: HtmlArtifact;
  escalation?: EscalationInfo; // kind === "escalation"
  /** True when this deliverable is a pending direction proposal (requires confirm_direction). */
  isProposal?: boolean;
  /** Set after verdict_recorded ack: 'accept' | 'discard' | 'redo' */
  verdict?: string;
  /** Original deliverable message id this item was refined from (deliverable_finalized). */
  refinedFrom?: number | null;
  /** kind === "system" roster notice: "joined" | "left" */
  rosterAction?: string;
  /** kind === "system": routing brief (need restatement + @-mention duty lines)
   *  from a routing frame's `announcement`. Rendered with mention chips. */
  isRouteAnnouncement?: boolean;
  /** role === "user": attachments sent with this message (session-only display echo —
   *  set client-side on send, never present on history-restored items). */
  attachments?: MessageAttachment[];
  /** PA-3 structured clarification card (from a `clarify_options` frame): question +
   *  2-4 one-click options. `answered` flips true once the user picks (disables the
   *  card). Session-only — a history reload shows the persisted compact text instead. */
  clarifyOptions?: { question: string; options: ClarifyOption[]; answered?: boolean };
}

/** A row from the server `history` frame. */
export interface ArslanHistoryRow {
  message_id: number;
  role: "user" | "arslan" | "spawn_summary";
  content: string;
  spawn_id: number | null;
}

// Server -> client frames on /ws/arslan
export type ArslanServerMessage =
  | { type: "history"; messages: ArslanHistoryRow[] }
  | { type: "proposal"; spawn_id: number; spawn_name: string | null }
  | { type: "routing"; spawn_id: number; spawn_name: string | null; announcement?: string | null }
  | { type: "auto_continue"; spawn_id: number; spawn_name?: string | null; remaining?: number }
  | { type: "stream_start"; source: "arslan" | "spawn"; spawn_id?: number | null }
  | { type: "stream_chunk"; content: string }
  // stream_end may carry an HTML deliverable packaged by the backend spawn-output
  // exit (HX-2): {kind:"html", filename, title, bytes, complete, content}. It rides
  // the SAME frame the store turns into the chat item. 🔒 Backend only.
  | {
      type: "stream_end";
      message_id: number | null;
      artifact?: { kind: string; filename?: string; title?: string; bytes?: number;
                   complete?: boolean; content?: string };
    }
  | { type: "suggest_create"; draft: SuggestDraft; task_brief?: string | null; overlaps?: OverlapInfo | null }
  | { type: "propose_invite"; spawn_id: number; reason: string }
  | { type: "propose_run_command"; call_id: string; command?: string; argv?: string[]; pretty: string; reason?: string }
  | { type: "spawn_meta"; arslan_message_id: number; spawn_id: number; assistant_message_id: number; task_brief: string; run_id?: number }
  | { type: "fact_saved"; content: string; sensitive: boolean }
  | { type: "message"; message_id: number; content: string; role: string }
  | { type: "spawn_created"; spawn_id: number; spawn_name: string; equipment?: Equipment; intro?: string | null }
  | { type: "tool_call"; tool: string; args_summary: string }
  | {
      type: "tool_result";
      tool: string;
      ok: boolean;
      summary: string;
      // Legacy SVG artifact carries `content`; the ECharts artifact carries `spec`
      // (a plain-JSON ECharts option object); the pptx artifact carries base64 file bytes.
      // All come ONLY from the backend.
      artifact?: { kind: string; content?: string; spec?: Record<string, unknown>;
                   filename?: string; bytes_b64?: string; slides?: number };
    }
  | { type: "escalation"; spawn_id: number; spawn_name: string | null; kind: string; need: string }
  | { type: "escalation_refused"; spawn_id: number; why: string }
  | { type: "escalation_resolved"; spawn_id: number; how: string; detail: string }
  | { type: "error"; code: string; message: string; recoverable?: boolean }
  | { type: "verdict_recorded"; spawn_id: number; action: string }
  | { type: "deliverable_finalized"; spawn_id: number; message_id: number; content: string; refined_from: number | null; spawn_name?: string }
  | { type: "roster_update"; members: { spawn_id: number; spawn_name: string | null; joined_via: string; status: string }[] }
  | { type: "roster_event"; action: string; spawn_id: number; spawn_name: string | null }
| { type: "attachment_stored"; spawn_name: string | null; chunks: number }
  | { type: "propose_staffing"; candidates: StaffingCandidate[]; create_draft: SuggestDraft | null }
  | { type: "clarify_options"; question: string; options: ClarifyOption[] }
  | { type: "suggest_update"; spawn_id: number; spawn_name: string;
      current: SpawnUpdateCurrent; changes: SpawnUpdateChanges; reason?: string }
  | { type: "spawn_updated"; spawn_id: number; spawn_name: string;
      applied: SpawnUpdateChanges; equipment?: Equipment };

export interface RosterMember {
  spawnId: number;
  spawnName: string | null;
  joinedVia: string;
  status: string;
}

export interface SuggestPrimaryResult {
  id: number;
  provider: string;
  rationale: string;
}

export interface CatalogCapabilities {
  cost: number;
  speed: number;
  tool_calling: number;
  reasoning: number;
  long_context: number;
}

export interface CatalogEntry {
  provider: string;
  capabilities: CatalogCapabilities;
  languages: Record<string, number>;
}

export interface RunStepDto {
  seq: number;
  kind: string;
  ref: Record<string, unknown>;
  detail: Record<string, unknown>;
  duration_ms: number | null;
}

export interface RunEvaluationDto {
  dimension: string;
  status: string;
  score: number;
  comment: string;
}

export interface RunDto {
  id: number;
  conversation_id: string;
  spawn_id: number | null;
  spawn_name: string | null;
  user_message: string;
  total_ms: number | null;
  task_tokens: number;
  status: string;
  overall_score: number | null;
  overall_badge: string | null;
  model: string | null;
  provider: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  tokens_estimated: boolean;
  error_kind: string | null;
  error_text: string | null;
  system_prompt: string | null;
  injected_kb: string | null;
  injected_kb_sources: string[] | null;
}

export interface RunDetailDto {
  run: RunDto;
  steps: RunStepDto[];
  evaluations: RunEvaluationDto[];
}

export interface KnowledgeSource { source: string; chunks: number; }
export interface IngestResult { source: string; chunks_added: number; }

/** Shared knowledge collection (layer A): CRUD, ingest, sources, spawn binding. */
export interface CollectionOut {
  id: number;
  name: string;
  description?: string | null;
  chunks: number;
  sources: number;
  spawn_ids: number[];
}

/** Embedding ops status: active provider/model, backfill counts, reindex + local-model download progress. */
export interface EmbeddingStatus {
  provider: string | null;
  model: string | null;
  embedded: number;
  pending: number;
  reindex: { running: boolean; done: number; total: number; error: string | null };
  local_model: { status: string; error: string | null };
}
export interface EvolveGate {
  passed: boolean;
  reason: string;
  aggregate: Record<string, unknown> | null;
}
export interface EvolveProposal {
  proposal_id: number | null;
  candidate_prompt: string | null;
  gate: EvolveGate;
  evidence: Record<string, unknown> | null;
}
export interface ConfirmResult {
  ok: boolean;
  reason?: string;
  spawn_id?: number;
  generation_level?: number;
}

export interface RunListItem {
  id: number;
  spawn_name: string | null;
  status: string;
  overall_score: number | null;
  overall_badge: string | null;
  total_ms: number | null;
  user_message: string;
  created_at?: string | null;
}

/** Per-spawn aggregate over scored runs (GET /runs/summary). */
export interface RunSpawnSummary {
  spawn_name: string;
  scored_count: number;
  avg_score: number | null;
  pass_rate: number | null; // % of scored runs with overall_score >= 7
}

/** One recent run for the score-trend chart (null score = unscored). */
export interface RunTrendPoint {
  id: number;
  overall_score: number | null;
  created_at?: string | null;
}

/** Aggregates for the evaluation-summary charts (GET /runs/summary). */
export interface RunSummary {
  scored_count: number;
  avg_score: number | null;
  pass_rate: number | null; // 0-100, null when nothing scored
  dimension_averages: Record<string, number | null>;
  per_spawn: RunSpawnSummary[];
  recent: RunTrendPoint[];
}

/** Per-spawn RED aggregate row (GET /runs/catalog). */
export interface CatalogSpawnDto {
  spawn_id: number | null;
  spawn_name: string | null;
  model: string | null;
  run_count: number;
  error_ratio: number;
  p95_ms: number | null;
  pass_rate: number | null;
  avg_score: number | null;
  tokens_sum: number;
  health: string;
  score_trend: number[];
  latency_trend: (number | null)[];
  error_trend: number[];
  rate_trend: number[];
}

/** Response for GET /runs/catalog — per-spawn RED + fleet rollup, worst-first. */
export interface RunCatalogDto {
  range: string;
  fleet: {
    run_count: number;
    error_ratio: number;
    p95_ms: number | null;
    pass_rate: number | null;
    tokens_sum: number;
  };
  spawns: CatalogSpawnDto[];
}

/** One deterministic threshold-rule finding (GET /runs/anomalies). */
export interface AnomalyDto {
  severity: string;
  kind: string;
  spawn_id: number | null;
  spawn_name: string | null;
  title: string;
  detail: string;
  since: string | null;
  run_id: number | null;
}

/** GET /runs/vitals — bucketed run-rate + error overlay + duration heatmap. */
export interface VitalsBucketDto { t: string; count: number; errors: number }
export interface RunVitalsDto {
  range: string;
  bucket_ms: number;
  total: number;
  error_ratio: number;
  p95_ms: number | null;
  buckets: VitalsBucketDto[];
  duration_bins: string[];
  duration_matrix: number[][];
}

/** GET /conversations/{id}/recap — runs + growth events on one timeline, desc. */
export interface RecapItemDto {
  kind: string;                 // run | distill | memory | skill | evolution | invite
  created_at: string | null;
  run_id?: number | null;
  spawn_name?: string | null;
  user_message?: string | null;
  overall_score?: number | null;
  total_ms?: number | null;
  ref?: Record<string, unknown> | null;
  summary?: string | null;
}
export interface RecapDto {
  summary: { run_count: number; avg_score: number | null; growth_count: number };
  items: RecapItemDto[];
}

/** GET /runs/timeline — per-spawn severity bands over time. */
export interface TimelineCellDto { sev: string; count: number; errors: number }
export interface TimelineSpawnDto { spawn_id: number | null; spawn_name: string | null; cells: TimelineCellDto[] }
export interface RunTimelineDto { range: string; buckets: string[]; spawns: TimelineSpawnDto[] }

export interface McpServer {
  id: number;
  label: string;
  command: string;
  args: string[];
  env: Record<string, string>; // masked on read
  status: string; // registered|connected|error
  last_error?: string | null;
  transport?: string;
  url?: string | null; // streamable-HTTP endpoint (transport === "http")
}

/** A self-authored skill candidate in the skill-forge loop. */
export interface SkillCandidate {
  id: number;
  key: string;
  name: string;
  category: string;
  description: string;
  status: "observing" | "proposed" | "promoted" | "rejected" | string;
  source: string;
  created_at: string;
  promoted_at: string | null;
}

/** Gate result from evaluating a skill candidate against a target spawn. */
export interface SkillGate {
  passed: boolean;
  reason: string;
  aggregate: Record<string, unknown> | null;
}

/** Result of POST /skills/candidates/{id}/evaluate. */
export interface SkillEvaluateResult {
  ok: boolean;
  status: string;
  gate: SkillGate;
  [key: string]: unknown;
}

/** Result of POST /skills/candidates/{id}/promote. */
export interface SkillPromoteResult {
  ok: boolean;
  key?: string;
  reason?: string;
}

/** Curator (Slice 3) usage/quality signal for one promoted self-authored skill. */
export interface CuratorFlag {
  key: string;
  name: string;
  equipped_spawns: number;
  usage: number;
  avg_score: number | null;
  flag: "unused" | "underperforming" | null;
  reason: string | null;
}

export interface McpTool {
  key: string;
  name: string;
  description: string;
  tier: string; // safe|orchestrator
  status: string; // registered|wired
  suggested_tier: string; // safe|orchestrator (UI hint)
  host_enabled: boolean; // Arslan (host) may use this MCP tool
}

export interface NoteDto {
  id: number; title: string; content: string; tags: string[];
  created_at: string | null; updated_at: string | null;
  backlinks?: { id: number; title: string }[];
}

/** Result of POST /conversations/{id}/distill — how many spawn chats were distilled. */
export interface DistillResult { ok: boolean; distilled_spawns: number }
/** Result of DELETE /conversations/{id} — per-table row counts removed. */
export interface DeleteResult { ok: boolean; deleted: Record<string, number> }
export interface NoteSuggestDto {
  suggestions: { target: string; kind: string; reason: string }[];
  tags: string[];
}
