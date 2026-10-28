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
  /** INB1: why it is not in effect (outside_content, setting_off, no_judgement, not_a_correction,
   *  conflicts, failed_repeatedly; a retired one keeps its reason, or says "retired"); null while active. */
  not_in_effect?: string | null;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });

export const lessonsApi = {
  list: () => request<Lesson[]>("/lessons"),
  /** Switch on or restore (active); undo or retire (archived — restorable). `expectedUpdatedAt`: the
   *  row Memory's sheet showed; one that changed since is refused (409, F4 of the #460 review). */
  setStatus: (id: number, status: "active" | "archived", expectedUpdatedAt?: string) => request<Lesson>(`/lessons/${id}/status`,
    json("POST", expectedUpdatedAt ? { status, expected_updated_at: expectedUpdatedAt } : { status })),
  pin: (id: number, pinned: boolean) => request<Lesson>(`/lessons/${id}/pin`, json("POST", { pinned })),
  remove: (id: number) => request(`/lessons/${id}`, { method: "DELETE" }),
};
