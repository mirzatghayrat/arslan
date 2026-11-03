/**
 * What an empty model slot actually does — two slots, two different meanings.
 *
 * v0.1.64 ROUTE1: there is no task routing, so no slot is "assigned by a strategy".
 * The router ("remembering facts") runs on the primary config; the vision slot, when
 * empty, leaves an image turn on the conversation's own model. Writing "follows your
 * main model" on the vision slot would be false for every conversation that picked a
 * model of its own.
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

const TWO = [cfg(1, "Main", true), cfg(2, "Cheap")];

describe("the two slots (ROUTE1: compaction and final answer are gone)", () => {
  it("declares exactly router and vision, each with a label AND a purpose key", () => {
    expect(MODEL_SLOTS.map((s) => s.id).sort()).toEqual(["router", "vision"]);
    for (const s of MODEL_SLOTS) {
      expect(s.purposeKey, s.id).toBeTruthy();
      expect(s.labelKey, s.id).toBeTruthy();
    }
  });

  it("gives every slot a distinct settings key", () => {
    const keys = MODEL_SLOTS.map((s) => s.settingsKey);
    expect(new Set(keys).size).toBe(MODEL_SLOTS.length);
  });
});

describe("router follows the primary", () => {
  it("names the primary config, not the first one", () => {
    const f = slotFallback("router", { configs: [cfg(2, "Cheap"), cfg(1, "Main", true)] });
    expect(f.kind).toBe("follows-primary");
    expect((f as { modelLabel: string }).modelLabel).toBe("Main");
  });
});

describe("vision follows the conversation, not the primary", () => {
  it("never claims to follow the main model", () => {
    // server/services/llm_factory.py: a conversation's own model takes its image
    // turns; the vision slot applies only to conversations without a choice.
    expect(slotFallback("vision", { configs: TWO }).kind).toBe("follows-conversation");
  });
});

describe("nothing configured", () => {
  it.each(["router", "vision"] as const)(
    "%s reports no-configs rather than an empty label",
    (slot) => {
      const f = slotFallback(slot, { configs: [] });
      expect(f.kind).toBe("no-configs");
      expect(f).not.toHaveProperty("modelLabel");
    },
  );
});

describe("the primary label", () => {
  it("falls back to the first config when none is flagged primary", () => {
    const f = slotFallback("router", { configs: [cfg(1, "Only")] });
    expect((f as { modelLabel: string }).modelLabel).toBe("Only");
  });

  it("uses provider and model when a config has no label", () => {
    const f = slotFallback("router", {
      configs: [{ id: 1, provider: "openai", model: "gpt-4o", is_primary: true }],
    });
    expect((f as { modelLabel: string }).modelLabel).toBe("openai (gpt-4o)");
  });

  it("uses provider and model when the label is only whitespace", () => {
    const f = slotFallback("router", {
      configs: [{ id: 1, label: "   ", provider: "openai", model: "gpt-4o", is_primary: true }],
    });
    expect((f as { modelLabel: string }).modelLabel).toBe("openai (gpt-4o)");
  });
});
