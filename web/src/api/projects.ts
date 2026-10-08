import { request } from "./client";
import type { ProjectTemplate } from "./companion";

/** 0.1.56 projects in two layers (server/api/projects.py, services/project_plan.py). */
export type Band = "shaping" | "doing" | "done";
export type Column = "idea" | "shaping" | "doing" | "done" | "dropped";

export interface Evidence {
  kind: "said" | "file" | "run" | "checkpoints" | string;
  quote?: string;
  path?: string;
  job_id?: string;
  level_id?: string;
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
export interface Plan {
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
}
export interface Board {
  cards: BoardCard[];
  counts: { paused: number; archived: number };
  shadow: { proposed: number; accepted: number; streak: number; ask_at: number; asked: boolean; auto_advance: boolean };
}
export interface ProjectEvent {
  id: string;
  kind: "tick" | "untick" | "proposal" | "advance" | "plan_change" | "stage" | "auto_ask";
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
  draft: (template: ProjectTemplate, finish_line: string, lang: string) =>
    request<{ levels: Level[]; source: "template" | "model" }>("/projects/draft", json("POST", { template, finish_line, lang })),
  plan: (projectId: string) => request<Plan>(`/projects/${id(projectId)}/plan`),
  savePlan: (projectId: string, expected_version: number, levels: Level[]) =>
    request<Plan>(`/projects/${id(projectId)}/plan`, json("PUT", { expected_version, levels })),
  tick: (projectId: string, checkpointId: string, on: boolean) =>
    request<Plan>(`/projects/${id(projectId)}/checkpoints/${id(checkpointId)}/${on ? "tick" : "untick"}`, { method: "POST" }),
  advance: (projectId: string) => request<Plan>(`/projects/${id(projectId)}/advance`, { method: "POST" }),
  decide: (projectId: string, proposalId: string, accept: boolean) =>
    request<Plan>(`/projects/${id(projectId)}/proposals/${id(proposalId)}/${accept ? "accept" : "decline"}`, { method: "POST" }),
  undo: (projectId: string, eventId: string) => request<Plan>(`/projects/${id(projectId)}/events/${id(eventId)}/undo`, { method: "POST" }),
  stage: (projectId: string, body: { stage?: "active" | "done" | "dropped"; paused?: boolean }) =>
    request<Plan>(`/projects/${id(projectId)}/stage`, json("PUT", body)),
  events: (projectId: string, limit = 20) => request<ProjectEvent[]>(`/projects/${id(projectId)}/events?limit=${limit}`),
  conversations: (projectId: string) =>
    request<{ conversation_id: string; messages: number; last_at: string | null; opening: string | null }[]>(`/projects/${id(projectId)}/conversations`),
  files: (projectId: string) =>
    request<{ folder: string | null; exists: boolean; entries: { name: string; dir: boolean }[]; truncated: boolean }>(`/projects/${id(projectId)}/files`),
};
