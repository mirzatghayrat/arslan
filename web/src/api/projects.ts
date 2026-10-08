import { request } from "./client";
import type { ProjectTemplate } from "./companion";

/** 0.1.56 projects in two layers (server/api/projects.py, services/project_plan.py). */
export type Band = "shaping" | "doing" | "done";
export type Column = "idea" | "shaping" | "doing" | "done" | "dropped";

export interface Evidence {
  kind: "said" | "file" | "run" | "checkpoints" | string;
  quote?: string;
  path?: string;
  /** file: the first matches, how many matched, and the pattern. */
  paths?: string[];
  count?: number;
  pattern?: string;
  /** run: the job and what it was asked to do. */
  job_id?: string;
  goal?: string;
  level_id?: string;
  conversation_id?: string;
  message_id?: number | null;
}
export interface Checkpoint {
  id?: string;
  text: string;
  expects?: { kind: "file"; pattern: string; min?: number } | null;
  state?: "todo" | "done";
  progress?: string | null;
  evidence?: Evidence | null;
  done_at?: string | null;
  done_by?: "user" | "arslan" | null;
}
export interface Level {
  id?: string;
  position?: number;
  name: string;
  description?: string;
  band: Band;
  clear_condition?: string;
  state?: "todo" | "current" | "cleared";
  habit?: boolean;
  started_at?: string | null;
  cleared_at?: string | null;
  checkpoints: Checkpoint[];
}
export type PlanDiffLine =
  | { op: "add"; level: string; band: Band }
  | { op: "remove"; level: string }
  | { op: "change"; level: string; added: string[]; removed: string[]; band: Band | null };
/** Arslan's proposed new plan (0.1.56 §7): what changes in the levels not cleared yet. */
export interface PlanProposal { id: string; diff: PlanDiffLine[]; reason: string; cleared: number }
export interface Plan {
  plan_proposal?: PlanProposal | null;
  project_id: string;
  version: number;
  stage: "idea" | "active" | "done" | "dropped";
  paused: boolean;
  column: Column;
  levels: Level[];
}
export interface Proposal {
  id: string;
  level: string;
  next: string | null;
  evidence: Evidence;
  moves_column: boolean;
  last: boolean;
}
export interface BoardCard {
  id: string;
  name: string;
  template: ProjectTemplate | null;
  kind: string;
  finish_line: string | null;
  stage: Plan["stage"];
  paused: boolean;
  column: Column;
  levels: { name: string; band: Band; state: Level["state"] }[];
  current: { position: number; name: string; started_at: string | null } | null;
  left: number;
  proposal: Proposal | null;
  done_at: string | null;
  has_plan: boolean;
  /** §9: quiet for too long — shown on the card only, never notified. */
  stall?: { days: number; usual: number | null; left: number } | null;
  /** The current level's next open checkpoint ("接着做"). */
  next?: { id: string; text: string } | null;
}
export interface Shadow {
  proposed: number; accepted: number; streak: number; ask_at: number; asked: boolean; auto_advance: boolean;
  /** §5: ask once, at `ask_at` kept in a row; offer to turn auto-advance off after 2 undos in a row. */
  ask_due?: boolean;
  offer_off?: boolean;
  /** The last answer was a miss (the board offers the optional line only then). */
  miss_is_latest?: boolean;
  last_miss?: { id: string; project_id: string; level: string | null; outcome: "declined" | "undone"; note: string | null; at: string } | null;
}
export interface Board {
  cards: BoardCard[];
  counts: { paused: number; archived: number };
  shadow: Shadow;
}
export interface PlanRule {
  id: string; template: ProjectTemplate | null; text: string; enabled: boolean; sources: string[]; created_at: string;
  value: { code?: "add_level" | "cut_scope" | "note" | "retro"; name?: string };
}
export interface PaceRow { template: ProjectTemplate; band: Band; levels: number; median_days: number | null; override_days: number | null }
export interface Retro {
  id: string;
  summary: string | null;
  source: "model" | "facts";
  rules: { text: string; kept: boolean }[];
  facts: {
    total_days: number | null; plan_changes: number; cut_checkpoints: number; slower: string[];
    levels: { level: string; band: Band; days: number | null; usual: number | null; slower: boolean }[];
  };
  created_at: string;
}
export interface Habits { shadow: Shadow; rules: PlanRule[]; pace: PaceRow[]; cleared_levels: number; pace_min_levels: number }
export interface ProjectEvent {
  id: string;
  kind: "tick" | "untick" | "proposal" | "advance" | "plan_change" | "plan_proposal" | "stage" | "handoff" | "retro";
  actor: "user" | "arslan";
  payload: Record<string, unknown> & { evidence?: Evidence | null; text?: string; level?: string; next?: string | null };
  outcome: string | null;
  created_at: string;
}
export interface TemplateInfo { key: ProjectTemplate; levels: { name: string; band: Band }[] }

const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });
const id = (s: string) => encodeURIComponent(s);

export const projectsApi = {
  board: () => request<Board>("/projects/board"),
  templates: (lang: string) => request<TemplateInfo[]>(`/project-templates?lang=${id(lang)}`),
  /** The template draft; with `refine`, one model call adapts `levels` to the finish line (0.1.56 §3.2). */
  draft: (template: ProjectTemplate, finish_line: string, lang: string, opts: { refine?: boolean; levels?: Level[] } = {}) =>
    request<{ levels: Level[]; source: "template" | "model"; refine_failed?: boolean }>("/projects/draft",
      json("POST", { template, finish_line, lang, ...opts })),
  plan: (projectId: string) => request<Plan>(`/projects/${id(projectId)}/plan`),
  savePlan: (projectId: string, expected_version: number, levels: Level[]) =>
    request<Plan>(`/projects/${id(projectId)}/plan`, json("PUT", { expected_version, levels })),
  tick: (projectId: string, checkpointId: string, on: boolean) =>
    request<Plan>(`/projects/${id(projectId)}/checkpoints/${id(checkpointId)}/${on ? "tick" : "untick"}`, { method: "POST" }),
  /** §4.4 "Hand to Arslan": a background job in that conversation that ends done ticks the checkpoint. */
  handoff: (projectId: string, checkpointId: string, conversationId: string) =>
    request<{ id: string }>(`/projects/${id(projectId)}/handoff`, json("POST", { checkpoint_id: checkpointId, conversation_id: conversationId })),
  advance: (projectId: string) => request<Plan>(`/projects/${id(projectId)}/advance`, { method: "POST" }),
  decide: (projectId: string, proposalId: string, accept: boolean) =>
    request<Plan>(`/projects/${id(projectId)}/proposals/${id(proposalId)}/${accept ? "accept" : "decline"}`, { method: "POST" }),
  /** §5: the optional line after a decline; it becomes a plan rule. */
  note: (projectId: string, proposalId: string, note: string) =>
    request<Plan>(`/projects/${id(projectId)}/proposal-notes/${id(proposalId)}`, json("POST", { note })),
  habits: () => request<Habits>("/project-habits"),
  /** §10: the retro of a Done project (null until written); writing it is one model call, on request. */
  retro: (projectId: string) => request<Retro | null>(`/projects/${id(projectId)}/retro`),
  writeRetro: (projectId: string, lang: string) => request<Retro>(`/projects/${id(projectId)}/retro`, json("POST", { lang })),
  keepRetroRule: (projectId: string, index: number) =>
    request<Retro>(`/projects/${id(projectId)}/retro/rules/${index}/keep`, { method: "POST" }),
  setRule: (ruleId: string, enabled: boolean) => request<Habits>(`/project-habits/rules/${id(ruleId)}`, json("PUT", { enabled })),
  setPace: (template: ProjectTemplate, band: Band, days: number | null) =>
    request<Habits>("/project-habits/pace", json("PUT", { template, band, days })),
  autoAdvance: (on: boolean, answered: "ask" | "offer" | "settings") =>
    request<Habits>("/project-habits/auto-advance", json("PUT", { on, answered })),
  decidePlan: (projectId: string, proposalId: string, accept: boolean) =>
    request<Plan>(`/projects/${id(projectId)}/plan-proposals/${id(proposalId)}/${accept ? "accept" : "decline"}`, { method: "POST" }),
  undo: (projectId: string, eventId: string) => request<Plan>(`/projects/${id(projectId)}/events/${id(eventId)}/undo`, { method: "POST" }),
  stage: (projectId: string, body: { stage?: "active" | "done" | "dropped"; paused?: boolean }) =>
    request<Plan>(`/projects/${id(projectId)}/stage`, json("PUT", body)),
  events: (projectId: string, limit = 20) => request<ProjectEvent[]>(`/projects/${id(projectId)}/events?limit=${limit}`),
  conversations: (projectId: string) =>
    request<{ conversation_id: string; messages: number; last_at: string | null; opening: string | null }[]>(`/projects/${id(projectId)}/conversations`),
  files: (projectId: string) =>
    request<{ folder: string | null; exists: boolean; entries: { name: string; dir: boolean }[]; truncated: boolean }>(`/projects/${id(projectId)}/files`),
};
