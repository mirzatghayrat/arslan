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
  /** Backend message id for verdict frames (spawnMessageId from the store item). */
  messageId?: number;
  routedTo?: {
    spawnId: string;
    spawnName: string;
  };
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
}

export interface AppSettings {
  llmProvider: string;
  llmModel: string;
  searchProvider: string;
  apiKeyLLM: string;
  apiKeySearch: string;
  language: string;
  theme: 'dark' | 'light';
  telemetry: boolean;
  spawnMode: 'auto' | 'interactive' | 'strict';
}
