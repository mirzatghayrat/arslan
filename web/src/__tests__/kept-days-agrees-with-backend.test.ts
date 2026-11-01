/**
 * Lockstep guard (Q7): how many days a handled reminder keeps its row in the window (`KEPT_DAYS`, web/src/lib/proactive.ts) vs the
 * days the server keeps a reminder open (`FRESH_DAYS`, arslan/proactive_policy.py). The window keeps its own copy instead of being
 * sent the table; a copy is defensible only with something that fails when the two drift, which is this (the review of PR 615 noted
 * nothing tied them). A source-text assertion is the right tool here: what is asserted is that two literals are equal.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { KEPT_DAYS } from "../lib/proactive";

const REPO = join(__dirname, "..", "..", "..");

describe("the window's KEPT_DAYS agrees with the server's FRESH_DAYS", () => {
  it("has the same kinds and the same days", () => {
    const src = readFileSync(join(REPO, "arslan/proactive_policy.py"), "utf8");
    const block = src.match(/^FRESH_DAYS\s*=\s*\{([^}]*)\}/m);
    if (!block) throw new Error("FRESH_DAYS not found: the backend module was restructured");
    const server = Object.fromEntries([...block[1].matchAll(/"(\w+)":\s*(\d+)/g)].map(([, kind, days]) => [kind, Number(days)]));
    expect(Object.keys(server)).toContain("job_followup");
    expect(KEPT_DAYS).toEqual(server);
  });
});
