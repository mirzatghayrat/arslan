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
}
export interface RegistrySkill {
  key: string; name: string; category: string; description: string;
  tier: string; status: string; assignable: boolean;
}
export interface RegistryCatalog { toolsets: RegistryToolset[]; skills: RegistrySkill[]; }

/** One step of a spawn's tool loop, paired from tool_call/tool_result frames. */
export interface ToolStep {
  tool: string;
  argsSummary: string;
  status: "running" | "ok" | "error";
  resultSummary?: string;
  /** SVG markup from a backend render_chart tool_result artifact. NEVER from LLM message text. */
  artifactSvg?: string;
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
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  timestamp?: string;
}

export interface SpawnDetail extends SpawnSummary {
  persona_role: string | null;
  persona_tone: string | null;
  system_prompt: string;
  messages: ChatMessage[];
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
}

export interface ProviderOption {
  key: string;
  label: string;
  base_url: string;
  default_model: string;
  native: boolean;
  models: string[];
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
}

export interface SuggestDraft {
  name: string;
  domain: string;
  capabilities: string[];
  persona_role?: string | null;
  persona_tone?: string | null;
  reason?: string | null;
}

export interface OverlapInfo {
  spawn_id: number;
  name: string;
  axes: string[];
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
  escalation?: EscalationInfo; // kind === "escalation"
  /** True when this deliverable is a pending direction proposal (requires confirm_direction). */
  isProposal?: boolean;
  /** Set after verdict_recorded ack: 'accept' | 'discard' | 'redo' */
  verdict?: string;
  /** Original deliverable message id this item was refined from (deliverable_finalized). */
  refinedFrom?: number | null;
  /** kind === "system" roster notice: "joined" | "left" */
  rosterAction?: string;
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
  | { type: "routing"; spawn_id: number; spawn_name: string | null }
  | { type: "stream_start"; source: "arslan" | "spawn"; spawn_id?: number | null }
  | { type: "stream_chunk"; content: string }
  | { type: "stream_end"; message_id: number | null }
  | { type: "suggest_create"; draft: SuggestDraft; task_brief?: string | null; overlaps?: OverlapInfo | null }
  | { type: "spawn_meta"; arslan_message_id: number; spawn_id: number; assistant_message_id: number; task_brief: string; run_id?: number }
  | { type: "fact_saved"; content: string; sensitive: boolean }
  | { type: "message"; message_id: number; content: string; role: string }
  | { type: "spawn_created"; spawn_id: number; spawn_name: string; equipment?: Equipment; intro?: string | null }
  | { type: "tool_call"; tool: string; args_summary: string }
  | { type: "tool_result"; tool: string; ok: boolean; summary: string; artifact?: { kind: string; content: string } }
  | { type: "escalation"; spawn_id: number; spawn_name: string | null; kind: string; need: string }
  | { type: "escalation_refused"; spawn_id: number; why: string }
  | { type: "escalation_resolved"; spawn_id: number; how: string; detail: string }
  | { type: "error"; code: string; message: string; recoverable?: boolean }
  | { type: "verdict_recorded"; spawn_id: number; action: string }
  | { type: "deliverable_finalized"; spawn_id: number; message_id: number; content: string; refined_from: number | null; spawn_name?: string }
  | { type: "roster_update"; members: { spawn_id: number; spawn_name: string | null; joined_via: string; status: string }[] }
  | { type: "roster_event"; action: string; spawn_id: number; spawn_name: string | null }
| { type: "attachment_stored"; spawn_name: string | null; chunks: number };

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
}

export interface RunDetailDto {
  run: RunDto;
  steps: RunStepDto[];
  evaluations: RunEvaluationDto[];
}

export interface KnowledgeSource { source: string; chunks: number; }
export interface IngestResult { source: string; chunks_added: number; }
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

export interface McpTool {
  key: string;
  name: string;
  description: string;
  tier: string; // safe|orchestrator
  status: string; // registered|wired
  suggested_tier: string; // safe|orchestrator (UI hint)
  host_enabled: boolean; // Arslan (host) may use this MCP tool
}
