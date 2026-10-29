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
  /** 0.1.58 §5: checkpoints still open in the level (absent when none). */
  open?: { id: string; text: string }[];
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
}
export interface Board {
  cards: BoardCard[];
  counts: { paused: number; archived: number };
}
export interface Retro {
  id: string;
  summary: string | null;
  source: "model" | "facts";
  facts: {
    total_days: number | null; plan_changes: number; cut_checkpoints: number;
    levels: { level: string; band: Band; days: number | null }[];
  };
  created_at: string;
}
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
  /** 0.1.58 §5: with checkpoints still open the server answers 409 open_checkpoints + the list
   *  until `leftover` says what happens to them (move to the next level, or drop). */
  advance: (projectId: string, choice?: { leftover: Leftover; note?: string }) =>
    request<Plan>(`/projects/${id(projectId)}/advance`, json("POST", choice ?? {})),
  decide: (projectId: string, proposalId: string, accept: boolean, leftover?: Leftover) =>
    request<Plan>(`/projects/${id(projectId)}/proposals/${id(proposalId)}/${accept ? "accept" : "decline"}`,
      json("POST", leftover ? { leftover } : {})),
  /** §10: the retro of a Done project (null until written); writing it is one model call, on request. */
  retro: (projectId: string) => request<Retro | null>(`/projects/${id(projectId)}/retro`),
  writeRetro: (projectId: string, lang: string) => request<Retro>(`/projects/${id(projectId)}/retro`, json("POST", { lang })),
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

/** 0.1.58 §5: what happens to a level's unfinished checkpoints when it is cleared early. */
export type Leftover = "move" | "drop";

/** The open checkpoints a 409 open_checkpoints carries, or null for any other error. */
export function openCheckpointsOf(cause: unknown): { id: string; text: string }[] | null {
  const detail = (cause as { status?: number; detail?: { code?: string; open?: { id: string; text: string }[] } })?.detail;
  return detail?.code === "open_checkpoints" && Array.isArray(detail.open) ? detail.open : null;
}
