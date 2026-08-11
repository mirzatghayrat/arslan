/**
 * What an empty model slot actually does — five slots, three different meanings.
 *
 * 🔴 Writing "follows your main model" on all five would be false in two places:
 * the router is pinned to the primary and never drifts, and synthesis follows
 * whatever model the conversation is already running on. A false line in the UI is
 * the same defect as a comment describing something that does not happen.
 *
 * The fixture that earns its place is "one config under a routing strategy". An
 * implementation that checks only the strategy passes every other case here and is
 * still wrong, because routing.select also returns the primary below two configs.
 */
import { describe, expect, it } from "vitest";

import { MODEL_SLOTS, slotFallback } from "../lib/modelSlots";

const cfg = (id: number, label: string, primary = false) => ({
  id,
  label,
  provider: "deepseek",
  model: "deepseek-chat",
  is_primary: primary,
});

const ONE = [cfg(1, "Main", true)];
const TWO = [cfg(1, "Main", true), cfg(2, "Cheap")];

describe("the five slots", () => {
  it("declares exactly five, each with a label AND a purpose key", () => {
    expect(MODEL_SLOTS).toHaveLength(5);
    for (const s of MODEL_SLOTS) {
      expect(s.purposeKey, s.id).toBeTruthy();
      expect(s.labelKey, s.id).toBeTruthy();
    }
  });

  it("gives every slot a distinct settings key", () => {
    const keys = MODEL_SLOTS.map((s) => s.settingsKey);
    expect(new Set(keys).size).toBe(5);
  });
});

describe("router is pinned, not following", () => {
  it("stays on the primary config even under a routing strategy", () => {
    // arslan/llm/routing.py pins the "router" role in JUDGMENT_ROLES: evaluation
    // and optimisation must never drift onto a cheaper model.
    const f = slotFallback("router", { strategy: "balanced", configs: TWO });
    expect(f.kind).toBe("pinned-primary");
    expect((f as { modelLabel: string }).modelLabel).toBe("Main");
  });
});

describe("synthesis follows the conversation, not the primary", () => {
  it("never claims to follow the main model", () => {
    // server/orchestrator/tool_loop.py:1046 replaces the adapter ONLY when the slot
    // is set; otherwise the tool loop keeps the one it already had.
    expect(
      slotFallback("synthesis", { strategy: "single", configs: TWO }).kind,
    ).toBe("follows-conversation");
    expect(
      slotFallback("synthesis", { strategy: "balanced", configs: TWO }).kind,
    ).toBe("follows-conversation");
  });
});

describe("the routable three", () => {
  it.each(["compaction", "title", "vision"] as const)(
    "%s follows the primary under the single strategy",
    (slot) => {
      const f = slotFallback(slot, { strategy: "single", configs: TWO });
      expect(f.kind).toBe("follows-primary");
      expect((f as { modelLabel: string }).modelLabel).toBe("Main");
    },
  );

  it.each(["compaction", "title", "vision"] as const)(
    "%s is routed under a routing strategy with two configs",
    (slot) => {
      expect(slotFallback(slot, { strategy: "balanced", configs: TWO }).kind).toBe(
        "routed",
      );
    },
  );

  it.each(["compaction", "title", "vision"] as const)(
    "%s still follows the primary when only ONE config exists",
    (slot) => {
      // 🔴 The discriminating fixture. routing.select returns the primary when
      // fewer than two configs exist, so a check that looks only at the strategy
      // would put "assigned by your routing strategy" on screen — and that is false
      // in what is probably the most common setup of all.
      expect(slotFallback(slot, { strategy: "balanced", configs: ONE }).kind).toBe(
        "follows-primary",
      );
    },
  );
});

describe("nothing configured", () => {
  it.each(["synthesis", "compaction", "title", "router", "vision"] as const)(
    "%s reports no-configs rather than an empty label",
    (slot) => {
      const f = slotFallback(slot, { strategy: "single", configs: [] });
      expect(f.kind).toBe("no-configs");
      expect(f).not.toHaveProperty("modelLabel");
    },
  );
});

describe("the primary label", () => {
  it("falls back to the first config when none is flagged primary", () => {
    const f = slotFallback("title", { strategy: "single", configs: [cfg(1, "Only")] });
    expect((f as { modelLabel: string }).modelLabel).toBe("Only");
  });

  it("uses provider and model when a config has no label", () => {
    const f = slotFallback("title", {
      strategy: "single",
      configs: [{ id: 1, provider: "openai", model: "gpt-4o", is_primary: true }],
    });
    expect((f as { modelLabel: string }).modelLabel).toBe("openai (gpt-4o)");
  });

  it("uses provider and model when the label is only whitespace", () => {
    const f = slotFallback("title", {
      strategy: "single",
      configs: [{ id: 1, label: "   ", provider: "openai", model: "gpt-4o", is_primary: true }],
    });
    expect((f as { modelLabel: string }).modelLabel).toBe("openai (gpt-4o)");
  });
});
