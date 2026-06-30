export interface Tool {
  id: string;
  name: string;
  description: string;
  emoji: string;
  category: 'standard' | 'advanced_locked';
  tier: 'tier-1' | 'tier-2' | 'tier-3';
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  emoji: string;
  category: 'standard' | 'advanced_locked';
}

export interface ToolActivity {
  id: string;
  toolName: string;
  emoji: string;
  status: 'running' | 'completed';
  action: string;
  outputSummary: string;
  collapsed: boolean;
  /** SVG markup from a backend render_chart tool_result artifact. NEVER from LLM message text. */
  artifactSvg?: string;
  /** ECharts option object from a backend render_chart tool_result artifact (kind: "echarts"). NEVER from LLM message text. */
  artifactChart?: Record<string, unknown>;
}

export interface Escalation {
  id: string;
  spawnName: string;
  issue: string;
  status: 'need_raised' | 'arslan_resolving' | 'resolved' | 'refused';
  resolutionMessage?: string;
}

export interface Message {
  id: string;
  sender: 'user' | 'arslan' | 'spawn';
  senderName: string;
  senderAvatar: string;
  text: string;
  timestamp: string;
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
  routedTo?: {
    spawnId: string;
    spawnName: string;
  };
  /** Roster notice: "joined" | "left" — present on system messages from roster_event frames. */
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
  escalation?: Escalation;
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
  detail: Record<string, unknown>;
  durationMs: number | null;
  isSlowest: boolean;
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
}

export interface AppSettings {
  searchProvider: string;
  apiKeySearch: string;
  githubToken: string;
  language: string;
  theme: 'dark' | 'light';
  telemetry: boolean;
  spawnMode: 'auto' | 'interactive' | 'strict';
  llmStrategy: 'single' | 'cost' | 'balanced' | 'performance';
  distillOnSessionEnd: boolean;
}
