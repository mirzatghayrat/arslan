import type { Spawn } from "../types";
import type { SpawnSummary } from "./client.types";

/**
 * Maps a backend SpawnSummary DTO to the UI Spawn shape used by AI Studio components.
 *
 * Key mappings:
 * - id: number  →  id: string (String(id))
 * - total_tasks: number  →  totalTasks: number
 * - capabilities: string[]  →  tools/skills (passthrough as tools; skills empty unless provided)
 * - status: backend has no status field, default to "idle"
 * - avatarEmoji: default "🤖"
 */
export function toUiSpawn(s: SpawnSummary & {
  status?: string;
  tools?: string[];
  skills?: string[];
  total_tasks?: number;
  description?: string;
}): Spawn {
  return {
    id: String(s.id),
    name: s.name,
    domain: s.domain ?? "",
    description: s.description ?? "",
    status: (s.status as Spawn["status"]) ?? "idle",
    avatarEmoji: "🤖",
    tools: s.tools ?? s.capabilities ?? [],
    skills: s.skills ?? [],
    totalTasks: s.total_tasks ?? 0,
  };
}
