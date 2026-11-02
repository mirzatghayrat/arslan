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
  /** L11-3b: where it stands with the folder's rules: the offer nobody answered yet (Add / Not now, through `rule`
   *  with `conversation_id`) or the line the card added (Open / Remove, through the listing and `removeFolderRule`).
   *  `file` is the name Overview's listing shows. null for "not now", "removed" or no offer. */
  rule?: { state: "offered" | "added"; file: string; conversation_id: string; line: string } | null;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });

export const lessonsApi = {
  list: () => request<Lesson[]>("/lessons"),
  /** Switch on or restore (active); undo or retire (archived — restorable). `expectedUpdatedAt`: the
   *  row Memory's sheet showed; one that changed since is refused (409, F4 of the #460 review).
   *  Switching on needs it (422 without it, #466 review); retiring does not. */
  setStatus: (id: number, status: "active" | "archived", expectedUpdatedAt?: string) => request<Lesson>(`/lessons/${id}/status`,
    json("POST", expectedUpdatedAt ? { status, expected_updated_at: expectedUpdatedAt } : { status })),
  pin: (id: number, pinned: boolean) => request<Lesson>(`/lessons/${id}/pin`, json("POST", { pinned })),
  remove: (id: number) => request(`/lessons/${id}`, { method: "DELETE" }),
  /** L11-2: the "make this a rule?" card: add the lesson to the folder's rules file, "not now", or take it back. */
  rule: (id: number, conversationId: string, action: "add" | "skip" | "remove") =>
    request<{ state: string; file?: string; in_file?: boolean }>(`/lessons/${id}/rule`, json("POST", { conversation_id: conversationId, action })),
  /** L11-3a: Overview's Remove, from the rules record (works after the lesson was deleted). `file` is the name the
   *  listing showed; the server finds it again among this conversation's files. `in_file` is false when the line
   *  had changed in the file: it is left there and no longer listed. */
  removeFolderRule: (conversationId: string, file: string, lessonId: number, line: string) =>
    request<{ state: string; file: string; in_file: boolean }>(`/conversations/${encodeURIComponent(conversationId)}/folder-rules/remove`,
      json("POST", { file, lesson_id: lessonId, line })),
  /** K10-1 / L11-0: the rules files this conversation follows, with their text, for Overview. */
  folderRules: (conversationId: string) =>
    request<{ enabled: boolean; files: { file: string; text: string; added?: { lesson_id: number; line: string }[] }[];
      notes?: string[] }>(
      `/conversations/${encodeURIComponent(conversationId)}/folder-rules`),
};
