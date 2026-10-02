/**
 * update_plan (0.1.50 S2) in the activity list: plain words, never the raw
 * tool key or the backend's English shorthand ("1/3 done") in a zh/ja UI.
 */
import { describe, expect, it } from "vitest";

import de from "../locales/de.json";
import en from "../locales/en.json";
import es from "../locales/es.json";
import fr from "../locales/fr.json";
import ja from "../locales/ja.json";
import zh from "../locales/zh.json";
import { humanizeOutcome, humanizeStep } from "../lib/toolHumanize";

const BUNDLES = { de, en, es, fr, ja, zh } as const;

const tFor = (bundle: unknown) => (key: string, vars?: Record<string, unknown>) => {
  const hit = key.split(".").reduce<unknown>(
    (node, part) => (node && typeof node === "object"
      ? (node as Record<string, unknown>)[part] : undefined),
    bundle,
  );
  if (typeof hit !== "string" || !hit.trim()) throw new Error(`missing locale string: ${key}`);
  return Object.entries(vars ?? {}).reduce(
    (acc, [k, v]) => acc.replaceAll(`{{${k}}}`, String(v)), hit);
};

describe("plan steps read as words in every locale", () => {
  for (const [lang, bundle] of Object.entries(BUNDLES)) {
    it(lang, () => {
      const t = tFor(bundle);
      const step = humanizeStep({ tool: "update_plan", argsSummary: "{}", status: "running" }, t);
      expect(step).not.toContain("update_plan");
      const outcome = humanizeOutcome({ tool: "update_plan", resultSummary: "1/3 done" }, t);
      expect(outcome).toContain("1/3");
      expect(outcome).not.toContain("done{{");
      if (lang !== "en") expect(outcome).not.toContain(" done");
    });
  }
});
