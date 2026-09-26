export const EXPERT_CHATS_KEY = "arslan.expertChats.v1";
export function restoreExpertChats(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(EXPERT_CHATS_KEY) ?? "[]");
    return Array.isArray(value) ? [...new Set(value.filter((id): id is string => typeof id === "string" && /^[1-9]\d{0,12}$/.test(id)))].slice(0, 500) : [];
  } catch { return []; }
}
export function saveExpertChats(ids: string[]) {
  try { localStorage.setItem(EXPERT_CHATS_KEY, JSON.stringify(ids.slice(0, 500))); } catch { /* optional UI metadata */ }
}
