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
  name_key?: string | null; description_key?: string | null;
  assignable: boolean; tools: RegistryTool[];
  /** P0-1 决定①b: run-time degradation (e.g. run_python running UNSANDBOXED via the escape
   * valve). When true, the capability page badges the toolset with `warning`. */
  degraded?: boolean; warning?: string | null; warning_code?: string | null;
}
export interface RegistrySkill {
  key: string; name: string; category: string; description: string;
  name_key?: string | null; description_key?: string | null;
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

/* ── S3-M3 cost visibility ─────────────────────────────────────────────────────
 * Honesty invariant (backend server/api/usage.py): usd is null whenever the cost
 * can't be known — unknown-price model or estimated tokens. $0 is reserved for
 * genuinely free (local) models; the UI must never render null as $0. */

/** Per-turn usage riding a terminal stream_end frame (backend _usage_frame).
 *  Only the /ws/arslan channel carries it — the direct spawn-chat channel's
 *  stream_end (protocol.stream_end) stays usage-free; its tokens are ledgered
 *  server-side under scope "direct_chat" instead. */
export interface StreamUsage {
  tokens_in: number | null;
  tokens_out: number | null;
  tokens_total: number;
  estimated: boolean;
  usd: number | null;
  /** Which model(s) answered this turn, busiest first. Empty when none ran.
   *  More than one entry means the turn used more than one model — the event that
   *  must not be silent now that per-task slots can route work elsewhere. */
  /** OPTIONAL on purpose: a frame recorded before this shipped genuinely does not
   *  carry it, and declaring it required would be the type asserting something
   *  about the wire that is not true. */
  models?: { model: string; provider: string | null }[];
  /** 0.1.58: how many model calls the turn made (why a short answer carries a large input). */
  calls?: number;
  /** 0.1.58 §6: the last call's input tokens — how full the context is (the composer's ring).
   *  0.1.63 K3: the whole input, cache reads and writes included. */
  last_input?: number | null;
  /** 0.1.63 K3: input tokens read from the provider's cache this turn; null when it reported none. */
  cache_read?: number | null;
  /** 0.1.63 K3: the turn's whole input (on Claude, uncached + cache read + cache write). */
  input_total?: number | null;
  /** 0.1.63 K4b: what the last request was made of, estimated by the server (the ring's breakdown;
   *  its total stays last_input). Null when no request was measured. */
  context_parts?: ContextParts | null;
}

/** 0.1.63 K4b: estimated tokens of each part of a request. */
export interface ContextParts {
  system: number;
  tools: number;
  context: number;
  history: number;
  turn: number;
}

/** 0.1.58 §1: GET /runs/{id}/process. */
/** 0.1.63 S3: what undoing a turn covers (GET /runs/{id}/checkpoint); S3b adds the conversation. */
export interface RunCheckpoint {
  exists: boolean;
  changed?: number;
  created?: number;
  skipped?: { path: string; reason: string }[];
  excluded?: string[];
  later?: number[];
  running?: boolean;
  restored_at?: number | null;
  conversation: boolean;
  /** Why the conversation can't be undone: none | job | not_own_turn | already | summarised | running | finishing. */
  reason: string | null;
  /** The newest message the undo would take back: sent with it, so it is held to what was shown. */
  last_message_id?: number;
  messages_after?: number;
  later_turns?: number;
  facts?: number;
}

/** POST /runs/{id}/checkpoint/restore {what: "conversation" | "both"}: `history` is the conversation now. */
export interface TurnUndone {
  conversation?: { conversation_id: string; messages: number; later_turns: number; facts: number;
    history: ArslanHistoryRow[] };
  files?: { later: number[] };
}

export interface RunProcessOut extends Partial<ProcessSummary> {
  run_id: number;
  status: string;
  /** INB7-b: when the run started and ended (UTC, "Z"); ended_at is null while it runs. Older backends omit both. */
  started_at?: string | null;
  ended_at?: string | null;
  entries: {
    kind: "note" | "tool";
    text?: string;
    tool?: string;
    ok?: boolean;
    ms?: number | null;
    /** INB7-b: when the step started (UTC, "Z"); null for a step recorded before steps kept their time. */
    at?: string | null;
    args_summary?: string;
    summary?: string;
    detail?: { view: string; error?: string | null; [key: string]: unknown };
    raw?: { args: string; result: string };
  }[];
}

/** 0.1.58 §1: a reply's footer row — steps, how many did not work, time, usage. */
export interface ProcessSummary {
  steps: number;
  failed: number;
  ms: number | null;
  usage?: StreamUsage | null;
}

/** One scope's slice of a conversation's cumulative usage (spawn/answer/router/…). */
export interface ScopeUsage {
  scope: string;
  tokens_total: number;
  usd: number | null;
}

/** GET /conversations/{id}/usage — cumulative usage for ONE conversation.
 *  usd_total is null when NOTHING was priceable (unknown ≠ free); usd_partial
 *  says some tokens carry no USD figure. */
export interface ConversationUsage {
  tokens_total: number;
  usd_total: number | null;
  usd_partial: boolean;
  estimated_any: boolean;
  by_scope: ScopeUsage[];
}

/** One provider×model×scope aggregate row of GET /usage/summary. */
export interface UsageSummaryRow {
  provider: string | null;
  model: string | null;
  scope: string;
  tokens_total: number;
  usd: number | null;
  estimated_any: boolean;
}

/** One day of the summary's daily-tokens series (UTC "YYYY-MM-DD"). */
export interface UsageDailyPoint {
  date: string;
  tokens_total: number;
}

/** GET /usage/summary?range=24h|7d|30d — fleet-wide usage, visibility only.
 *  not_covered lists the LLM call sites that don't feed the ledger yet — the
 *  summary never pretends full coverage. */
export interface UsageSummary {
  range: string;
  rows: UsageSummaryRow[];
  daily: UsageDailyPoint[];
  not_covered: string[];
  /** 0.1.50 Activity dashboard (absent from older backends). */
  tokens_total?: number;
  usd_total?: number | null;
  estimated_any?: boolean;
  runs?: UsageRuns;
  bin_seconds?: number;
  duration_bands?: string[];
  bins?: UsageBin[];
}

/** What the work in the range did: answers, background jobs, scheduled runs. */
export interface UsageRuns {
  total: number; done: number; failed: number; stopped: number; running: number;
  p50_ms: number | null; p95_ms: number | null;
}

/** One time slice: work started in it, how it ended, how long finished work took. */
export interface UsageBin {
  start_ts: number;          // epoch seconds
  runs: number;
  failed: number;
  tokens_total: number;
  durations: number[];       // finished runs per duration band
  /** 0.1.58 hover card; absent on older backends. */
  p50_ms?: number | null;
  max_ms?: number | null;
  usd?: number | null;
  models?: { model: string; tokens: number }[];
}

/** One row of GET /scheduled-tasks (S3-M4). Mirrors ScheduledTaskOut. */
export interface ScheduledTaskDto {
  id: number;
  name: string;
  prompt: string;
  spawn_id: number | null;
  /** Joined display name; null when the spawn was deleted. */
  spawn_name: string | null;
  conversation_id: string | null;
  schedule_kind: "interval" | "cron" | string;
  interval_s: number | null;
  cron: string | null;
  enabled: boolean;
  last_fired_at: string | null;
  next_due_at: string | null;
  consecutive_failures: number;
  /** Non-null ONLY on the 3-fail auto-pause (manual pause leaves it null). */
  paused_reason: string | null;
  created_at: string | null;
  /** Latest run outcome ("ok"|"error"|"skipped_overlap"); null = no runs yet OR in flight. */
  last_outcome: string | null;
}

/** One row of GET /scheduled-tasks/{id}/runs — execution history. */
export interface ScheduledTaskRunDto {
  id: number;
  started_at: string | null;
  finished_at: string | null;
  /** "ok" | "error" | "skipped_overlap"; null = in flight. */
  outcome: string | null;
  /** runs.id — links to RunReplay. */
  run_id: number | null;
  reason: string | null;
}

/** POST /scheduled-tasks body (ScheduledTaskCreateIn). Server validates the
 *  schedule (interval floor 900s / cron grammar) — client mirrors loosely. */
export interface ScheduledTaskCreateBody {
  name: string;
  prompt: string;
  /** 0.1.44: omitted = Arslan runs it. */
  spawn_id?: number | null;
  schedule_kind: "interval" | "cron";
  interval_s?: number | null;
  cron?: string | null;
  /** null/empty = dedicated conversation (scheduled-{id}). */
  conversation_id?: string | null;
}

/** PUT /scheduled-tasks/{id} body — partial patch of the create fields. */
export type ScheduledTaskUpdateBody = Partial<ScheduledTaskCreateBody>;

/** One step of a spawn's tool loop, paired from tool_call/tool_result frames. */
export interface ToolStep {
  artifacts?: StoredArtifact[];
  /** 0.1.58 §1: "note" = what Arslan said before its next tool call (the tool loop's
   *  narration frame) — shown between steps, never part of the answer. */
  kind?: "note";
  text?: string;
  /** Client clock: when the call went out, and how long it took. */
  startedAt?: number;
  ms?: number;
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

export interface StoredArtifact {
  kind: "file";
  run_id: number;
  filename: string;
  title: string;
  bytes: number;
  sha256: string;
  media_type: string;
  url: string;
  /** One file's identity across a run's versions (server artifact_store; BR2). */
  logical_key?: string;
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
  first_run_seen?: boolean;
  search_provider: string;
  search_base_url: string;
  search_provider_role?: string; // "" | "only" | "backup" (0.1.63 D5)
  search_api_key: string; // masked on read
  github_token: string; // masked on read
  llm_strategy?: string;
  orchestrator_shell_enabled?: string; // "true" | "false"
  shell_confirm_policy?: string; // "ask_all" | "ask_risky"
  shell_policy_switch_notice?: string; // v0.1.63: "pending" after migration 0070 switched this user, then "seen"
  background_job_budget?: string; // "lean" | "standard" | "ample" (0.1.43)
  task_usd_cap?: string; // K4a: the per-task dollar cap, as text ("" = $2)
  workspace_dir?: string;   // "" = unset = file tools not offered
  workspace_other_volume?: boolean; // S3b: on another volume than Arslan's data: its changes can't be undone
  heartbeat_enabled?: string;     // "true" | "false"
  heartbeat_checklist?: string;
  show_technical_details?: string; // "true" | "false" (0.1.58)
  heartbeat_interval_s?: string;
  lan_discovery_enabled?: string; // "true" | "false"
  ssh_enabled?: string; // "true" | "false"
  default_read_enabled?: string; // "true" | "false" (default-ON: absent = on)
  folder_rules_enabled?: string; // K10-1: "true" | "false" (default-ON: absent = on)
  voice_input_locale?: string;   // BCP-47, "" = follow the UI language
  voice_mode?: string;            // "off" | "push_to_talk" | "conversation" (default push_to_talk)
  voice_endpoint_silence_ms?: string; // integer ms as a string (default "900")
  /** Embedding provider override: "" (or absent) = auto, "local", or a provider-config id. */
  embedding_config_id?: string;
  synthesis_config_id?: string;
  synthesis_model?: string;
  compaction_model?: string;
  router_model?: string;
  vision_model?: string;
  compaction_config_id?: string;
  router_config_id?: string;
  vision_config_id?: string;
  keep_awake_enabled?: boolean;
  desktop_notifications_enabled?: boolean;
  island_enabled?: boolean;
  terminal_sandbox_enabled?: boolean;
  memory_in_conversations?: boolean;
  learned_practices_take_effect?: boolean;
  phone_bridge_enabled?: boolean;
  /** Comma-separated BCP-47 tags for image text recognition. Empty = follow
   *  the interface language plus English. */
  ocr_languages?: string;
  /** Days a run's sensitive/bulky debug detail is kept before the boot sweep redacts it. Default 30. */
  run_debug_retention_days?: number;
  /** S4.1-C: whether the inbound MCP server (exposing Arslan's read-only tools
   *  to external MCP clients like Claude Code/Codex) is enabled. Default off. */
  mcp_server_enabled?: boolean;
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
  /** Honest key state from the backend so the UI can tell a genuinely-absent key
   *  from one that is STORED but undecryptable (encrypted under a now-changed
   *  ARSLAN_SECRET_KEY). Absent on legacy payloads → treated as 'unset'. */
  key_status?: 'set' | 'unset' | 'undecryptable';
  is_primary: boolean;
  /** Verdict of the last real chat test — the only evidence that means anything.
   *  "ok" | "failed", or null/absent when never tested. A build predating
   *  migration 0043 may still carry a retired probe word here; anything
   *  unrecognised reads as "never tested" rather than as broken. */
  last_health?: 'ok' | 'failed' | string | null;
  /** Naive-UTC ISO of that test (no timezone suffix — append "Z" before parsing). */
  last_health_at?: string | null;
  /** Human-readable reason when it failed, persisted so it survives a remount. */
  last_health_detail?: string | null;
}

/** One model from GET /settings/provider-configs/{id}/models. */
export interface ModelInfo {
  id: string;
  display_name: string | null;
  context_window: number | null;
  /** Subset of ["tools", "vision", "reasoning"]. */
  capabilities: string[];
  source: string;
  /** 0.1.58 §6: USD per million tokens, when the provider says (OpenRouter does). */
  price_in?: number;
  price_out?: number;
}

/** GET /settings/provider-configs/{id}/models — dynamic model catalog.
 *  `fetched_at` is naive-UTC ISO (no timezone suffix); append "Z" before parsing. */
export interface ModelListResult {
  models: ModelInfo[];
  fetched_at: string | null;
  stale: boolean;
  error: string | null;
  source: string;
}

// WebSocket wire messages (server -> client)
export type ServerMessage =
  | { type: "question"; node_id: string; text: string; options: string[] | null; multi_select: boolean; hint: string }
  | { type: "progress"; step: number; total: number; node_id: string }
  | { type: "build_complete"; spawn_id: number; spawn_name: string }
  | { type: "history"; messages: { message_id: number; role: string; content: string }[] }
  // run_id (S3-M1): present only on recorded runs — the cancel target for POST /runs/{id}/cancel.
  | { type: "stream_start"; message_id: number; run_id?: number }
  | { type: "stream_chunk"; content: string }
  | { type: "stream_end"; message_id: number }
  | { type: "message"; message_id: number; content: string; role: string }
  | { type: "error"; code: string; message: string; recoverable?: boolean; message_i18n?: Record<string, string> }
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
/** 0.1.42 background job, as the `job_update` frame describes it. */
export type JobOutcome = "done" | "partial" | "blocked" | "stopped" | "interrupted" | "out_of_budget";
/** 0.1.43: which limit ended a job, when one did. */
export interface JobBudgetStop { reason: string; used: number | null; limit: number | null; tier?: string }
export interface JobCriterion { id: string; description: string; status: string }
export interface JobCard {
  jobId: string;
  goal: string;
  phase: "queued" | "running" | "finished";
  step: string;
  outcome: JobOutcome | null;
  detail: string;
  budget?: JobBudgetStop | null;
  criteria: JobCriterion[];
}

/** D1 (0.1.55): one thing Arslan noticed and remembered (or wants to) after a turn. */
export interface RememberedFact {
  content: string;
  sensitive: boolean;
  entryId?: string | null;
  version?: number | null;
  /** "active" took effect (undoable); "proposed" waits for the user in Memory. */
  status: "active" | "proposed";
  /** INB2: a waiting one names its proposal and why it waits (sensitive, external_seen, not_present or
   *  confirmation_required). Only a "sensitive" one is asked about in the chat, bound to this proposal. */
  proposalId?: number | null;
  reason?: string | null;
}

/** What the install-and-retry card shows (server/services/capability_flow.card_for). */
export interface CapabilityCard {
  kind: "mcp" | "skill"; name: string; summary: string; source_url: string | null; repo: string | null;
  version: string | null; license: { spdx: string | null; read_from: string | null };
  stars: number | null; pushed_days: number | null; runtime: "uv" | "node" | "mcpb" | "remote" | "skill";
  runtime_download: { name: string; size_mb: number } | null; remote_host: string | null; network: boolean;
  folders: string[]; keys: { name: string; secret: boolean; required: boolean; description: string }[];
  why: string; retry: string;
  /** UNI1b (#586 review F2): a skill's characters that show nothing, in its text and references. */
  hidden?: { count: number; runs: string[]; more: number };
}
/** The save-a-skill card (v0.1.64 CAP2a, server/services/skill_forge.propose): the SKILL.md the model wrote, shown
 *  whole before anything is saved. Same frame and answers as the install card; told apart by `kind`. */
export interface AuthoredSkillCard {
  kind: "authored"; key: string; name: string; description: string; body: string; why: string;
  /** This conversation read a page, a file or another tool's result: the text may carry what that said. The
   *  saved skill is marked so (#472 F1, F2); since the user's D2 it is read unframed like every skill, so the
   *  card is the check. */
  outside: boolean;
}
export interface CapabilityResult { state: "on" | "failed" | "blocked"; name: string; tools: number;
  sourceId: string | null; stage?: string; code?: string; detail?: string }

export interface ArslanThreadItem {
  id: number;
  kind: "message" | "fact" | "system" | "job" | "lesson" | "plan" | "capability";
  /** kind === "capability" (0.1.57): how an install the user approved ended. */
  capabilityResult?: CapabilityResult;
  /** kind === "plan" (0.1.56 §7): Arslan's proposed new plan for this conversation's project. */
  planProposal?: import("./projects").PlanProposal & { projectId: string };
  /** kind === "job": the background job whose live card sits at this point in the
   *  thread; the card's state lives in the store's `jobs` map. On a message, the
   *  job this result came from. */
  jobId?: string;
  /** A job's result message: the outcome the server checked it against. */
  jobOutcome?: JobOutcome | null;
  role: "user" | "arslan" | "spawn";
  content: string;
  spawnId?: number | null;
  spawnName?: string | null;
  sensitive?: boolean; // kind === "fact"
  /** kind === "fact" (D1, 0.1.55): everything remembered in this turn, shown as one quiet line. */
  facts?: RememberedFact[];
  /** kind === "fact" (K2b): the reply its turn ended with (the frame's `reply_message_id`). Facts
   *  are looked for after the turn, so one may arrive once the next message is in; it still goes
   *  under that reply. */
  replyMessageId?: number | null;
  /** A user message forwarded from a paired iPhone (history row source "phone"). */
  fromPhone?: boolean;
  /** kind === "lesson" (0.1.52 S5): the practice just learned. */
  lesson?: { id: number; status: string; notInEffect?: string | null };
  runId?: number | null; // trace+eval replay id (stream_end / history row)
  toolSteps?: ToolStep[]; // replies: folded tool activity
  /** HTML deliverable from the stream_end frame's kind:"html" artifact (HX-2 channel).
   *  🔒 Populated ONLY from the backend frame, NEVER from LLM message text. */
  artifactHtml?: HtmlArtifact;
  /** S3-M1: true when this item is the partial output of a cancelled run
   *  (finalized from the live bubble by a run_cancelled frame). */
  cancelled?: boolean;
  /** S3-M3: the turn's usage from the terminal stream_end frame — drives the
   *  bubble's usage chip. Absent on cancelled/usage-free turns. */
  usage?: StreamUsage;
  /** 0.1.58 §1: how long the turn took (client clock, live turns). */
  elapsedMs?: number;
  /** 0.1.58 §1: the footer row from a history row (a reloaded conversation). */
  processSummary?: ProcessSummary;
  /** 0.1.58 §2: the files the turn produced, from a history row. */
  files?: StoredArtifact[];
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
  /** S3-M2: run linkage (ArslanMessage.run_id, set at finalize) — restores the
   *  RunReplay entry point after a reload. Always emitted; null when unlinked. */
  run_id?: number | null;
  /** 0.1.42: set on a background job's result — its checked outcome. */
  job_outcome?: JobOutcome | null;
  /** Mobile bridge: "phone" when a paired iPhone sent it; null/absent = the window. */
  source?: string | null;
  /** 0.1.58 §1: the reply's footer row (steps, time, model, usage), from its Run. */
  process?: ProcessSummary;
  /** 0.1.58 §2: the files the reply produced — its file cards after a reload. */
  files?: StoredArtifact[];
}

// Server -> client frames on /ws/arslan
export type ArslanServerMessage =
  | import("./tasks").TaskFrame
  | { type: "history"; messages: ArslanHistoryRow[] }
  /** 0.1.58 §1: what Arslan said before its next tool call (tool loop narration). */
  | { type: "note"; text: string }
  /** 0.1.59: every 15 s of a turn — the server is still on it (liveness only, never replayed). */
  | { type: "working"; elapsed_s: number }
  /** 0.1.59: this window's message waits for the conversation's current turn; then it starts. */
  | { type: "queued" }
  // K9b: `inserted` — the message was added to the turn that is running (not a turn of its own).
  | { type: "dequeued"; inserted?: boolean }
  // run_id (S3-M1): present only on recorded (spawn) runs — the cancel target for
  // POST /runs/{id}/cancel. Omitted on unrecorded streams.
  | { type: "stream_start"; source: "arslan" | "spawn"; spawn_id?: number | null; run_id?: number; temporary?: boolean }
  | { type: "stream_chunk"; content: string }
  // S3-M1: the server cancelled this run mid-flight. message_id is present when a
  // partial spawn_summary (已中断 marker) was persisted server-side.
  | { type: "run_cancelled"; run_id: number; message_id?: number }
  // S3-M2 reattach: sent between the history push and the journal replay when the
  // conversation has an in-flight run — arms the stop button before any stream frame.
  | { type: "run_in_progress"; run_id: number }
  // stream_end may carry an HTML deliverable packaged by the backend spawn-output
  // exit (HX-2): {kind:"html", filename, title, bytes, complete, content}. It rides
  // the SAME frame the store turns into the chat item. 🔒 Backend only.
  // S3-M3: terminal stream_ends also carry the turn's usage (tokens + honest usd);
  // omitted on paths that never opened a usage-collecting scope.
  | {
      type: "stream_end";
      message_id: number | null;
      temporary?: boolean;
      run_id?: number;
      usage?: StreamUsage;
      artifact?: { kind: string; filename?: string; title?: string; bytes?: number;
                   complete?: boolean; content?: string };
    }
  | { type: "suggest_create"; draft: SuggestDraft; task_brief?: string | null; overlaps?: OverlapInfo | null }
  | { type: "propose_invite"; spawn_id: number; reason: string }
  | ({ type: "propose_run_command"; call_id: string; command?: string; argv?: string[]; pretty: string; reason?: string; remote_host?: string; fingerprints?: string[]; background?: boolean; sandbox?: "outside" | "retry"; why?: string } & CardV2Fields)
  | { type: "propose_enroll_node"; call_id: string; name: string; host: string; user: string; fingerprints: string[] }
  | ({ type: "propose_workspace_write"; call_id: string; workspace: string; action: string; path: string; background?: boolean } & CardV2Fields)
  | ({ type: "propose_schedule"; call_id: string; name: string; when: string; prompt?: string; background?: boolean } & CardV2Fields)
  // 0.1.57 §3.1: add a capability and retry — answered only in this window (it may carry a key).
  | ({ type: "propose_capability"; call_id: string } & (CapabilityCard | AuthoredSkillCard))
  | { type: "capability_result"; call_id: string | null; source_id: string | null; state: "on" | "failed" | "blocked";
      name: string; tools: number; stage?: string; code?: string; detail?: string }
  | ({ type: "propose_action"; call_id: string; kind: ActionKind | (string & {}); target: string;
      detail: string; background?: boolean } & CardV2Fields)
  | { type: "fact_saved"; content: string; sensitive: boolean; entry_id?: string | null; version?: number | null; reply_message_id?: number }
  | { type: "memory_proposed"; content: string; sensitive: boolean; entry_id?: string | null; version?: number | null; reply_message_id?: number;
      proposal_id?: number | null; reason?: string | null }
  | { type: "plan_proposed"; project_id: string; proposal_id: string; diff: import("./projects").PlanDiffLine[]; reason: string; cleared: number }
  | { type: "lesson_learned"; lesson: { id: number; text: string; status: string; not_in_effect?: string | null } }
  // source "phone": the paired iPhone's message, shown live in a window open on its conversation.
  | { type: "message"; message_id: number; content: string; role: string; job_id?: string; outcome?: JobOutcome | null;
      source?: string | null }
  // A card shown in more than one place (a background job's, or a turn the iPhone started)
  // was decided — by this window, another, or the phone — or expired: close this copy.
  | { type: "card_resolved"; call_id: string; outcome: "approved" | "declined" | "expired"; by?: "phone" | "mac" | "inbox" | "island" }
  | { type: "job_update"; job_id: string; conversation_id: string; goal: string;
      phase: "queued" | "running" | "finished"; step: string; outcome: JobOutcome | null;
      detail: string; budget?: JobBudgetStop | null; criteria: JobCriterion[] }
  | { type: "job_spoken"; job_id: string; outcome: JobOutcome | null; goal: string }
  | { type: "tool_call"; tool: string; args_summary: string }
  | {
      type: "tool_result";
      tool: string;
      ok: boolean;
      summary: string;
      artifacts?: StoredArtifact[];
      // Legacy SVG artifact carries `content`; the ECharts artifact carries `spec`
      // (a plain-JSON ECharts option object); the pptx artifact carries base64 file bytes.
      // All come ONLY from the backend.
      artifact?: { kind: string; content?: string; spec?: Record<string, unknown>;
                   filename?: string; bytes_b64?: string; slides?: number };
    }
  | { type: "error"; code: string; message: string; recoverable?: boolean; message_i18n?: Record<string, string> }
  | { type: "propose_staffing"; candidates: StaffingCandidate[]; create_draft: SuggestDraft | null }
  | { type: "clarify_options"; question: string; options: ClarifyOption[] }
  | { type: "suggest_update"; spawn_id: number; spawn_name: string;
      current: SpawnUpdateCurrent; changes: SpawnUpdateChanges; reason?: string };

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
  no_learning?: boolean;
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
  /** M4 final review I-1: full deliverable text — present for scheduled (and
   * replay) runs whose conversation is unreachable from the sidebar; null for
   * plain live runs. */
  final_output: string | null;
}

export interface RunDetailDto {
  artifacts?: StoredArtifact[];
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
  /** NULL-or-STALE rows when a provider is active — a stale row is ALSO counted in
   * `embedded`, so `embedded + pending` is not the corpus size. Use `total`. */
  pending: number;
  /** real corpus size (COUNT of knowledge_chunks). Optional because an older backend
   * does not send it; the UI falls back rather than inventing a denominator. */
  total?: number;
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

export interface RunListItem {
  id: number;
  /** Stable identifier; null once the spawn is deleted (the run survives it). */
  spawn_id: number | null;
  spawn_name: string | null;
  status: string;
  overall_score: number | null;
  overall_badge: string | null;
  total_ms: number | null;
  user_message: string;
  created_at?: string | null;
  /** 0.1.58: where the work came from; older backends omit it (treated as chat). */
  origin?: "chat" | "job" | "scheduled" | "phone" | "browser";
  model?: string | null;
  tokens?: number | null;
  /** INB7-b: still running with a card open in its conversation, so it waits on you. Older backends omit it. */
  waiting?: boolean;
  /** INB7-b: when it ended (naive UTC, like created_at); a run the boot sweep interrupted has this and no total_ms. */
  ended_at?: string | null;
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
  /** USER DATA — never part of a translatable string, interpolated separately. */
  spawn_name: string | null;
  /** Locale keys + their numbers. The server used to send assembled Chinese
   *  sentences, which an English interface displayed verbatim because nothing
   *  downstream could translate them. */
  title_key: string;
  detail_key: string | null;
  params: Record<string, string | number>;
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
  /** Server-level host consent (user ruling 2026-08-18): connect = usable by Arslan. */
  host_allowed?: boolean;
  /** Real expose ("Allow for spawns") state, toolset-derived — no longer write-only. */
  exposed?: boolean;
  label: string;
  command: string;
  args: string[];
  env: Record<string, string>; // masked on read
  status: string; // registered|connected|error
  last_error?: string | null;
  transport?: string;
  url?: string | null; // streamable-HTTP endpoint (transport === "http")
  /** 0.1.61 §B1: the state the supervisor stored, and the state it is shown in (server `_to_dict`).
   *  `shown` is one of ready, starting, failed, parked, needs_auth, off (WB1-2 reads it). */
  state?: string | null;
  shown?: string;
}

export interface McpTool {
  key: string;
  name: string;
  /** The name through the server's name rule (UNI1a): what the page shows. */
  shown?: string;
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

/** Result of DELETE /conversations/{id} — per-table row counts removed. */
export interface DeleteResult { ok: boolean; deleted: Record<string, number> }
export interface NoteSuggestDto {
  suggestions: { target: string; kind: string; reason: string }[];
  tags: string[];
}

/** A machine enrolled for SSH (P3c). Nothing here is secret: a host key is
 *  public, and the key Arslan signs with never leaves the backend. */
/** Settings › iPhone (docs/specs/mobile-bridge-protocol.md §6.1). */
/** `state` (mobile-bridge-protocol §3.3): "connecting" until the Bridge has heard from the phone; absent from an older Bridge. */
export interface PhoneDevice { device_id: string; name: string; paired_at?: string | null; last_seen?: string | null; state?: "connecting" | "connected" | null }
export interface PhoneRequest { request_id: string; pairing_id?: string; phone_id?: string; phone_name?: string }
export interface PhoneCode { uri: string; qr_png: string; expires_at: string }
export interface PhoneStatus {
  connected: boolean;
  bridge: { device_id?: string; version?: string; protocol?: number };
  devices: PhoneDevice[];
  pending: PhoneRequest[];
  code: PhoneCode | null;
}

export interface SshNode {
  id: number;
  name: string;
  host: string;
  user: string;
  fingerprints: string[];
  created_at: string | null;
  last_used_at: string | null;
}

/** One command Arslan ran on another machine. Kept even after the machine is
 *  revoked — forgetting a machine must not erase what was done to it. */
export interface SshAuditEntry {
  id: number;
  at: string | null;
  node_name: string | null;
  host: string;
  user: string;
  command: string;
  exit_code: number | null;
  ok: boolean;
  error: string | null;
  conversation_id: string | null;
}

/** What a confirmation card for an action asks about (0.1.45 browser / Mac;
 * 0.1.53 Mac apps through Arslan Hands; 0.1.61: looking at an app and acting in it is one
 * `desktop_app` card, for this task, the conversation or always; a risky button every time). */
export type ActionKind = "browser_site" | "mac_shortcut" | "mac_script" | "desktop_app" | "desktop_risky";

/** 0.1.61 §A4: what a card from the permission layer carries (server permissions._ask). All absent
 *  on an old frame, which is shown and answered exactly as before. `expires_at` is Unix seconds. */
export interface CardV2Fields {
  options?: string[];
  always_label?: string;
  title?: string;
  perm_kind?: string;
  /** The model's one-line reason, if any: for a kind the card has no words for, it is the question (spec §A4). */
  why?: string;
  expires_at?: number;
  dedupe?: string;
}
