/**
 * Which task uses which model — and, when a slot is empty, what ACTUALLY happens.
 *
 * v0.1.64 ROUTE1: there is no task routing. Every role runs on the conversation's own model, else the primary, and
 * only two slots are left (the compaction and final-answer slots follow the conversation's model now). Their empty
 * meanings still differ, so this file decides them once instead of in a copy of an if-statement per slot:
 *
 *   router  "remembering facts" (judgments, lessons, turn facts): empty runs on the primary config.
 *   vision  an image turn of a conversation with no model of its own: empty runs on that conversation's model,
 *           which is the primary (a conversation's own model takes its image turns either way, server-side).
 */

export type SlotId = "router" | "vision";

/** 0.1.58 §6: the slot's model override key (settingsKey with ConfigId → Model). */
export const modelKeyOf = (key: SlotSettingsKey) => key.replace("ConfigId", "Model") as "routerModel" | "visionModel";

export type SlotSettingsKey = "routerConfigId" | "visionConfigId";

export interface ModelSlot {
  id: SlotId;
  settingsKey: SlotSettingsKey;
  labelKey: string;
  /** One line saying what this slot controls. Unexplained dropdowns are controls nobody dares touch. */
  purposeKey: string;
}

/** Declaration order is render order. */
export const MODEL_SLOTS: ModelSlot[] = [
  {
    id: "vision",
    settingsKey: "visionConfigId",
    labelKey: "settings.slotLabelVision",
    purposeKey: "settings.slotPurposeVision",
  },
  {
    id: "router",
    settingsKey: "routerConfigId",
    labelKey: "settings.slotLabelRouter",
    purposeKey: "settings.slotPurposeRouter",
  },
];

export interface SlotConfig {
  id: number;
  label?: string;
  provider: string;
  model: string;
  is_primary?: boolean;
}

export type SlotFallback =
  | { kind: "no-configs" }
  | { kind: "follows-primary"; modelLabel: string }
  | { kind: "follows-conversation" };

function primaryLabel(configs: SlotConfig[]): string {
  const p = configs.find((c) => c.is_primary) ?? configs[0];
  return p.label?.trim() ? p.label : `${p.provider} (${p.model})`;
}

export function slotFallback(slot: SlotId, opts: { configs: SlotConfig[] }): SlotFallback {
  const { configs } = opts;
  if (configs.length === 0) return { kind: "no-configs" };
  if (slot === "vision") return { kind: "follows-conversation" };
  return { kind: "follows-primary", modelLabel: primaryLabel(configs) };
}
