import { useAuthStore } from "../stores/authStore";
import type {
  AppSettings,
  EvolutionStats,
  SpawnDetail,
  SpawnSummary,
  TemplateInfo,
  UserFact,
} from "../types";

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const resp = await fetch(`${BASE}${path}`, {
    method: init.method ?? "GET",
    ...init,
    headers,
  });

  if (resp.status === 204) return undefined as T;

  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail ?? detail;
    } catch {
      // keep default
    }
    throw new ApiError(detail, resp.status);
  }
  return (await resp.json()) as T;
}

export const api = {
  health: () => request<{ status: string; version: string }>("/health"),
  listSpawns: () => request<SpawnSummary[]>("/spawns"),
  getSpawn: (id: number) => request<SpawnDetail>(`/spawns/${id}`),
  deleteSpawn: (id: number) => request<void>(`/spawns/${id}`, { method: "DELETE" }),
  updateConfig: (id: number, body: Partial<SpawnDetail>) =>
    request<SpawnDetail>(`/spawns/${id}/config`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  getEvolution: (id: number) => request<EvolutionStats>(`/spawns/${id}/evolution`),
  sendFeedback: (
    id: number,
    body: { message_id?: number; user_action: string; edits?: Record<string, unknown> },
  ) =>
    request<void>(`/spawns/${id}/feedback`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listTemplates: () => request<TemplateInfo[]>("/templates"),
  getSettings: () => request<AppSettings>("/settings"),
  updateSettings: (body: Partial<AppSettings>) =>
    request<AppSettings>("/settings", { method: "PUT", body: JSON.stringify(body) }),
  listFacts: () => request<UserFact[]>("/facts"),
  addFact: (body: { content: string; sensitive?: boolean }) =>
    request<UserFact>("/facts", { method: "POST", body: JSON.stringify(body) }),
  updateFact: (id: number, body: { content?: string; sensitive?: boolean }) =>
    request<UserFact>(`/facts/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteFact: (id: number) => request<void>(`/facts/${id}`, { method: "DELETE" }),
};
