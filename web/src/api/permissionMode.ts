import { request } from "./client";

export type PermissionMode = "plan" | "ask" | "ask_risky" | "full_access";
/** Why "Ask only when risky" runs as "Ask every step" for now ("" = it doesn't). */
export type FallbackReason = "" | "sandbox_off" | "home_folder" | "no_checkpoint";
/** S5a: `own` (null = the default), `chosen` (own or the default, narrowed by a parent), `mode` (what applies now),
 *  `fallback`, and `previous` (what Plan's Start restores; null = the default). */
export type ModeState = {
  own: PermissionMode | null; chosen: PermissionMode; mode: PermissionMode;
  fallback: FallbackReason; previous: PermissionMode | null;
};

const path = (id: string) => `/conversations/${encodeURIComponent(id)}/permission-mode`;

/** S5a: this conversation's permission mode. Set from the desktop window only. */
export const permissionModeApi = {
  get: (id: string) => request<ModeState>(path(id)),
  set: (id: string, mode: PermissionMode) =>
    request<ModeState>(path(id), { method: "PUT", body: JSON.stringify({ mode }) }),
  start: (id: string) => request<ModeState>(`${path(id)}/start`, { method: "POST" }),
};
