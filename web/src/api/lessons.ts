import { request } from "./client";

/** 0.1.52 S5: a practice Arslan learned (server/services/lessons.py). */
export interface Lesson {
  id: number;
  situation: string;
  advice: string;
  polarity: "do" | "avoid";
  source: "user_correction" | "detour" | "machine_quirk";
  status: "active" | "proposed" | "stale" | "archived";
  pinned: boolean;
  /** "situation → advice", as Arslan sees it. */
  text: string;
  recalled: number;
  followed: number;
  succeeded: number;
  failed: number;
  evidence: Record<string, unknown>;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });

export const lessonsApi = {
  list: () => request<Lesson[]>("/lessons"),
  /** Accept or restore (active); undo or retire (archived — restorable). */
  setStatus: (id: number, status: "active" | "archived") => request<Lesson>(`/lessons/${id}/status`, json("POST", { status })),
  pin: (id: number, pinned: boolean) => request<Lesson>(`/lessons/${id}/pin`, json("POST", { pinned })),
  remove: (id: number) => request(`/lessons/${id}`, { method: "DELETE" }),
};
