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
  spawn_id: number;
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
  /** Honest key state from the backend so the UI can tell a genuinely-absent key
   *  from one that is STORED but undecryptable (encrypted under a now-changed
   *  ARSLAN_SECRET_KEY). Absent on legacy payloads → treated as 'unset'. */
  key_status?: 'set' | 'unset' | 'undecryptable';
  is_primary: boolean;
  /** P4 tri-state connectivity of the last probe (null/absent = never probed):
   *  "reachable_models" | "reachable_no_list" | "unreachable". */
  last_health?: string | null;
  /** Naive-UTC ISO of the last probe (no timezone suffix — append "Z" before parsing). */
  last_health_at?: string | null;
}

/** One model from GET /settings/provider-configs/{id}/models. */
export interface ModelInfo {
  id: string;
  display_name: string | null;
  context_window: number | null;
  /** Subset of ["tools", "vision", "reasoning"]. */
  capabilities: string[];
  source: string;
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
  // run_id (S3-M1): present only on recorded runs — the cancel target for POST /runs/{id}/cancel.
  | { type: "stream_start"; message_id: number; run_id?: number }
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
  /** S3-M1: true when this item is the partial output of a cancelled run
   *  (finalized from the live bubble by a run_cancelled frame). */
  cancelled?: boolean;
  /** S3-M3: the turn's usage from the terminal stream_end frame — drives the
   *  bubble's usage chip. Absent on cancelled/usage-free turns. */
  usage?: StreamUsage;
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
  /** S3-M2: run linkage (ArslanMessage.run_id, set at finalize) — restores the
   *  RunReplay entry point after a reload. Always emitted; null when unlinked. */
  run_id?: number | null;
}

// Server -> client frames on /ws/arslan
export type ArslanServerMessage =
  | { type: "history"; messages: ArslanHistoryRow[] }
  | { type: "proposal"; spawn_id: number; spawn_name: string | null }
  | { type: "routing"; spawn_id: number; spawn_name: string | null; announcement?: string | null }
  | { type: "auto_continue"; spawn_id: number; spawn_name?: string | null; remaining?: number }
  // run_id (S3-M1): present only on recorded (spawn) runs — the cancel target for
  // POST /runs/{id}/cancel. Omitted on unrecorded streams.
  | { type: "stream_start"; source: "arslan" | "spawn"; spawn_id?: number | null; run_id?: number }
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
      usage?: StreamUsage;
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
  /** M4 final review I-1: full deliverable text — present for scheduled (and
   * replay) runs whose conversation is unreachable from the sidebar; null for
   * plain live runs. */
  final_output: string | null;
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

/* ── S2 evolution: the promotion card + inbox (spec §E7) ──────────────────────
 * Mirrors the backend GateResult.user_facing() shape EXACTLY. real_delta and
 * synthetic_delta are the ONLY win-rate deltas — there is deliberately no merged
 * field, and the UI must never compute one (real/synthetic never merged). */

/** One corpus's win/loss/tie + exact binomial p-value + Wilson 95% CI. */
export interface DeltaStat {
  wins: number;
  losses: number;
  ties: number;
  n: number; // non-tie pairs (wins + losses)
  win_rate: number; // 0..1
  p_value: number;
  ci95: [number, number];
}

/** One holdout pair's trace-linkable evidence row. `overall`/`per_dim` verdicts:
 * "b" = candidate won, "a" = baseline won (candidate lost), else tie. */
export interface EvidencePair {
  task_hash: string;
  corpus_label: "real" | "synthetic";
  source_ref: number | { synth_id: number; version: number } | null;
  split_side: string;
  baseline_run_id: number | null;
  candidate_run_id: number | null;
  base_out_len: number;
  cand_out_len: number;
  per_dim: Record<string, "a" | "b" | "tie">;
  overall: "a" | "b" | "tie";
  position_sensitive: boolean;
}

/** The holdout-only evidence payload (GateResult.user_facing). */
export interface ProposalEvidence {
  passed?: boolean;
  reason?: string;
  flags: string[];
  real_delta: DeltaStat;
  synthetic_delta: DeltaStat;
  evidence_tier: "strong" | "medium" | "weak";
  pairs: EvidencePair[];
  excluded_count: number;
  protected_run_ids?: number[];
}

/** One inbox row (GET /evolution/proposals) — summary only. */
export interface ProposalListItem {
  id: number;
  spawn_id: number;
  status: string; // open | proposed | promoted | rejected | stale
  gate_passed: boolean;
  base_prompt_sha: string | null;
  real_delta: DeltaStat | null;
  synthetic_delta: DeltaStat | null;
  evidence_tier: string | null;
  flags: string[];
  created_at: string | null;
  promoted_at: string | null;
}

/** Full card payload (GET /evolution/proposals/{id}). `base_prompt` is the spawn's
 * CURRENT canonical system_prompt — the honest diff base; `is_stale` = it has
 * drifted from the gate's baseline (base_prompt_sha). */
export interface ProposalDetail {
  id: number;
  spawn_id: number;
  spawn_name: string | null;
  status: string;
  gate_passed: boolean;
  generation_level: number | null;
  base_prompt_sha: string | null;
  base_prompt: string | null;
  candidate_prompt: string;
  is_stale: boolean;
  evidence: ProposalEvidence;
  estimate: EvolveEstimate | null;
  actual: Record<string, unknown> | null;
  created_at: string | null;
  promoted_at: string | null;
}

/** GET /spawns/{id}/evolve/estimate — honest lower-bound cost estimate. */
export interface EvolveEstimate {
  pairs: number;
  dispatches: number;
  judge_calls: number;
  optimizer_calls: number;
  synth_calls: number;
  est_tokens: number;
  lower_bound: boolean;
}

/** 202 response for POST /spawns/{id}/evolve (background job). */
export interface EvolveEnqueued {
  attempt_id: number | null;
}

/**
 * Stable machine verdict for the evolution eligibility diagnosis (E9-b). The panel maps each
 * to a localized `evolution.diag.verdict_${code}` sentence. `holdout_via_synthetic_topup` is
 * INFORMATIONAL — a thin real holdout is no longer a blocker; the mint=True top-up fills it at
 * evolve time. This union is the EXACT 1:1 set of codes the service can emit.
 */
export type VerdictCode =
  | "in_flight_hung"
  | "drought_no_runs"
  | "drought_non_replayable"
  | "drought_too_few"
  | "baseline_flooring"
  | "holdout_via_synthetic_topup"
  | "gate_failure"
  | "skipped_budget"
  | "eligible_looking";

/** GET /spawns/{id}/evolution/diagnosis — read-only evolution eligibility for one spawn. */
export interface SpawnDiagnosis {
  spawn_id: number;
  spawn_name: string;
  generation_level: number;
  total_scored: number;
  replayable: number;
  non_replayable: number;
  offending_tools: Record<string, number>;
  baseline_started_at: string | null;
  scored_ge_baseline: number;
  corpus_total: number;
  holdout_ceiling: number;
  real_holdout: number;
  effective_holdout: number;
  propose_count: number;
  corpus_excluded: number;
  min_holdout_n: number;
  consecutive_fails: number;
  threshold: number;
  count_since_last_attempt: number;
  auto_eligible: boolean;
  open_proposals: number;
  auto_on: boolean;
  max_est_tokens: number | null;
  last_attempts: {
    id: number;
    outcome: string | null;
    reason: string;
    started_at: string | null;
    finished_at: string | null;
  }[];
  verdict_code: VerdictCode;
  verdict_params: Record<string, unknown>;
}

/** POST /evolution/proposals/{id}/refresh. */
export interface RefreshResult {
  ok: boolean;
  status?: string | null;
  refreshed?: boolean;
  gate_passed?: boolean | null;
  flags?: string[];
  reason?: string | null;
  proposal_id?: number | null;
  new_tasks?: number | null;
}

/** POST /evolution/proposals/{id}/rollback. */
export interface RollbackResult {
  ok: boolean;
  reason?: string | null;
  spawn_id?: number | null;
  generation_level?: number | null;
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
