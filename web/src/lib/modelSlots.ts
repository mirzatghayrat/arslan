/**
 * Which task uses which model — and, when a slot is empty, what ACTUALLY happens.
 *
 * 🔴 THE FIVE SLOTS DO NOT SHARE ONE EMPTY-STATE MEANING, and this file exists so
 * that fact is decided once instead of in five copies of an if-statement:
 *
 *   router      the "router" role is in JUDGMENT_ROLES (arslan/llm/routing.py), so it
 *               is pinned to the primary config and never drifts to a cheaper model.
 *               That pinning is deliberate — evaluation and optimisation must not be
 *               the place the app economises.
 *   synthesis   server/orchestrator/tool_loop.py:1046 swaps the adapter ONLY when the
 *               slot is set; otherwise the tool loop keeps the adapter it already had.
 *               That is the CONVERSATION's model, which is not the primary.
 *   the rest    fall through to build_adapter(role=…) -> routing.select(), which can
 *               genuinely land on a different config.
 *
 * Saying "follows your main model" on all five would be false in two of them, and a
 * false line in the UI is the same defect as a comment describing something that does
 * not happen.
 */

export type SlotId = "synthesis" | "compaction" | "title" | "router" | "vision";

export type SlotSettingsKey =
  | "synthesisConfigId"
  | "compactionConfigId"
  | "titleConfigId"
  | "routerConfigId"
  | "visionConfigId";

export interface ModelSlot {
  id: SlotId;
  settingsKey: SlotSettingsKey;
  labelKey: string;
  /** One line saying what this slot controls. Five unexplained dropdowns are five
   *  controls nobody dares touch. */
  purposeKey: string;
}

/** Declaration order is render order: the two a user meets first, then the rest. */
export const MODEL_SLOTS: ModelSlot[] = [
  {
    id: "compaction",
    settingsKey: "compactionConfigId",
    labelKey: "settings.slotLabelCompaction",
    purposeKey: "settings.slotPurposeCompaction",
  },
  {
    id: "title",
    settingsKey: "titleConfigId",
    labelKey: "settings.slotLabelTitle",
    purposeKey: "settings.slotPurposeTitle",
  },
  {
    id: "synthesis",
    settingsKey: "synthesisConfigId",
    labelKey: "settings.slotLabelSynthesis",
    purposeKey: "settings.slotPurposeSynthesis",
  },
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
  | { kind: "pinned-primary"; modelLabel: string }
  | { kind: "follows-primary"; modelLabel: string }
  | { kind: "routed" }
  | { kind: "follows-conversation" };

function primaryLabel(configs: SlotConfig[]): string {
  const p = configs.find((c) => c.is_primary) ?? configs[0];
  return p.label?.trim() ? p.label : `${p.provider} (${p.model})`;
}

export function slotFallback(
  slot: SlotId,
  opts: { strategy: string; configs: SlotConfig[] },
): SlotFallback {
  const { strategy, configs } = opts;

  if (configs.length === 0) return { kind: "no-configs" };
  if (slot === "synthesis") return { kind: "follows-conversation" };
  if (slot === "router") {
    return { kind: "pinned-primary", modelLabel: primaryLabel(configs) };
  }

  // 🔴 BOTH conditions, not just the strategy. routing.select returns the primary
  // when fewer than two configs exist:
  //     if strategy == "single" or role in JUDGMENT_ROLES or len(configs) < 2
  // so "one config plus a balanced strategy" is NOT routed — and checking only the
  // strategy would put a false sentence on screen in a very ordinary setup.
  const routed = strategy !== "single" && configs.length >= 2;
  return routed
    ? { kind: "routed" }
    : { kind: "follows-primary", modelLabel: primaryLabel(configs) };
}
