/** M7-#4 — the SKILL.md heading contract is LITERAL and cross-layer.
 *
 * The backend accepts "## Decision Rules" and legacy "## 决策规则".
 * UI hints must name one supported literal token, not an arbitrary translation.
 * Backend compatibility is covered by test_skill_heading_compatibility.py.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const LOCALES = ["en", "zh", "ja", "de", "es", "fr"] as const;

function locale(lang: string): Record<string, unknown> {
  return JSON.parse(
    readFileSync(join(__dirname, "..", "locales", `${lang}.json`), "utf8"),
  );
}

function dig(obj: unknown, path: string[]): string {
  let cur: unknown = obj;
  for (const p of path) cur = (cur as Record<string, unknown>)[p];
  return cur as string;
}

describe("SKILL.md contract tokens (backend-literal in every locale)", () => {
  it.each([...LOCALES])("%s: forge bodyPlaceholder is the exact skeleton", (lang) => {
    const v = dig(locale(lang), ["forge", "fields", "bodyPlaceholder"]);
    expect(v).toContain("## Trigger");
    expect(v).toContain(lang === "zh" ? "## 决策规则" : "## Decision Rules");
  });

  it.each([...LOCALES])("%s: forge bodyHint names both literal tokens", (lang) => {
    const v = dig(locale(lang), ["forge", "fields", "bodyHint"]);
    expect(v).toContain("## Trigger");
    expect(v).toContain(lang === "zh" ? "## 决策规则" : "## Decision Rules");
  });

  it.each([...LOCALES])("%s: capabilities skill_body_label names both tokens", (lang) => {
    const v = dig(locale(lang), ["capabilities", "skill_body_label"]);
    expect(v).toContain("## Trigger");
    expect(v).toContain(lang === "zh" ? "## 决策规则" : "## Decision Rules");
  });
});
