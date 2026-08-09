/**
 * The last mile: a search failure reaches the screen as WHICH failure.
 *
 * The backend has kept the HTTP status since before this round — 429 arrived as
 * "http 429" — and this file's subject replaced every web_search error with one
 * generic sentence, so none of it was ever visible. Classification on one end and a
 * shrug on the other is the same as no classification, which is why the backend test
 * and this one are two halves of a single requirement.
 *
 * The three named failures have three DIFFERENT remedies — wait, top up, replace the
 * key — so the test that matters most is the one asserting they read differently from
 * each other. Identical wording for different remedies is the defect itself.
 */
import { describe, expect, it } from "vitest";

import en from "../locales/en.json";
import { humanizeStep, searchProvenance } from "../lib/toolHumanize";

const LANGS = ["de", "en", "es", "fr", "ja", "zh"] as const;
const KEYS = ["search_fail", "search_fail_rate", "search_fail_quota", "search_fail_key",
              "search_via", "search_via_best_effort"] as const;

/** Resolves the REAL shipped English: the words are the deliverable. */
const t = (key: string, vars?: Record<string, unknown>) => {
  const hit = key.split(".").reduce<unknown>(
    (node, part) => (node && typeof node === "object"
      ? (node as Record<string, unknown>)[part] : undefined),
    en as unknown,
  );
  if (typeof hit !== "string" || !hit.trim()) throw new Error(`missing locale string: ${key}`);
  return Object.entries(vars ?? {}).reduce(
    (acc, [k, v]) => acc.replaceAll(`{{${k}}}`, String(v)), hit);
};

const fail = (summary: string) =>
  humanizeStep({ tool: "web_search", argsSummary: "", resultSummary: summary, status: "error" }, t);

describe("a search failure says which failure", () => {
  it("names a rate limit", () => {
    expect(fail("search failed: rate-limited")).toMatch(/rate/i);
  });

  it("names an exhausted quota", () => {
    expect(fail("search failed: quota-exhausted")).toMatch(/quota/i);
  });

  it("names a rejected key", () => {
    expect(fail("search failed: key-rejected")).toMatch(/key/i);
  });

  it("gives the three remedies three different sentences", () => {
    // THE assertion. Each of these needs the reader to do something different; one
    // sentence for all three is the state this replaces.
    const seen = ["rate-limited", "quota-exhausted", "key-rejected"].map(
      (c) => fail(`search failed: ${c}`));
    expect(new Set(seen).size).toBe(3);
  });

  it("falls back to the generic line for a failure it has no advice about", () => {
    // Deliberate. Guessing a remedy for an unrecognised code would read as
    // understanding we do not have — worse than saying little.
    expect(fail("search failed: http 418")).toBe(en.activity.search_fail);
    expect(fail("search failed: network error")).toBe(en.activity.search_fail);
  });

  it("no longer promises a retry the code does not make", () => {
    // The old copy said "retrying differently" for EVERY failure. Only the
    // rate-limited path retries, and that string says so itself; the generic one must
    // not claim something that does not happen.
    expect(en.activity.search_fail).not.toMatch(/retry|retrying/i);
  });
});

describe("provenance", () => {
  it("names the provider", () => {
    expect(searchProvenance("tavily", false, t)).toContain("tavily");
  });

  it("marks the keyless fallback as best effort", () => {
    const s = searchProvenance("duckduckgo", true, t);
    expect(s).toContain("duckduckgo");
    expect(s).toMatch(/best effort/i);
  });

  it("does not mark a key-backed provider as best effort", () => {
    expect(searchProvenance("tavily", false, t)).not.toMatch(/best effort/i);
  });

  it("says nothing when the provider is unknown", () => {
    expect(searchProvenance(undefined, false, t)).toBe("");
  });
});

describe("locale coverage", () => {
  it("ships all six strings in all six languages, none blank", async () => {
    for (const lang of LANGS) {
      const mod = await import(`../locales/${lang}.json`);
      const activity = (mod.default as Record<string, Record<string, string>>).activity;
      for (const k of KEYS) {
        expect(typeof activity[k], `${lang}.${k}`).toBe("string");
        expect(activity[k].trim().length, `${lang}.${k}`).toBeGreaterThan(0);
      }
    }
  });

  it("keeps the provider placeholder in every language", async () => {
    // A translation that drops {{provider}} turns "via duckduckgo" into "via", which
    // is provenance that names nobody.
    for (const lang of LANGS) {
      const mod = await import(`../locales/${lang}.json`);
      const activity = (mod.default as Record<string, Record<string, string>>).activity;
      expect(activity.search_via, lang).toContain("{{provider}}");
      expect(activity.search_via_best_effort, lang).toContain("{{provider}}");
    }
  });
});
