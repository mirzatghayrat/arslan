import { describe, expect, it } from "vitest";
import de from "../locales/de.json";
import en from "../locales/en.json";
import es from "../locales/es.json";
import fr from "../locales/fr.json";
import ja from "../locales/ja.json";
import zh from "../locales/zh.json";

function flatten(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" && v !== null
      ? flatten(v as Record<string, unknown>, `${prefix}${k}.`)
      : [`${prefix}${k}`],
  );
}

describe("locale parity", () => {
  const enKeys = flatten(en).sort();
  it.each([
    ["zh", zh],
    ["ja", ja],
    ["es", es],
    ["de", de],
    ["fr", fr],
  ])("%s has the same keys as en", (_name, locale) => {
    expect(flatten(locale as Record<string, unknown>).sort()).toEqual(enKeys);
  });
});
