export interface SpawnSummary {
  id: number;
  name: string;
  domain: string;
  capabilities: string[];
  template_used: string | null;
  generation_level: number;
  created_at: string;
  updated_at: string;
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

/** A renderable item in the unified Arslan thread. */
export interface ArslanThreadItem {
  id: number;
  kind: "message" | "fact";
  role: "user" | "arslan" | "spawn";
  content: string;
  spawnId?: number | null;
  spawnName?: string | null;
  sensitive?: boolean; // for kind === "fact"
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
  | { type: "routing"; spawn_id: number; spawn_name: string | null }
  | { type: "stream_start"; source: "arslan" | "spawn"; spawn_id?: number | null }
  | { type: "stream_chunk"; content: string }
  | { type: "stream_end"; message_id: number }
  | { type: "suggest_create"; draft: SuggestDraft }
  | { type: "fact_saved"; content: string; sensitive: boolean }
  | { type: "spawn_created"; spawn_id: number; spawn_name: string }
  | { type: "error"; code: string; message: string; recoverable?: boolean };
