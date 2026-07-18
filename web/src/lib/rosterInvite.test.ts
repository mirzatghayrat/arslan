/**
 * BUG2 cross-layer contract: a CARD accept must carry origin:'invite_card' (the
 * backend's honest joined_no_pending notice fires on nothing else), while a Ledger
 * pull must NOT — it promised membership only.
 *
 * The source guard is the load-bearing half: without it, "normalizing" the four
 * roster_invite sends in App.tsx into one shape silently resurrects BUG2 with every
 * backend and frontend test still green (backend tests build their own frames).
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { cardAcceptInvite, ledgerInvite } from "./rosterInvite";

describe("roster_invite frame builders", () => {
  it("card accepts carry origin:'invite_card'", () => {
    expect(cardAcceptInvite(7)).toEqual({
      type: "roster_invite",
      spawn_id: 7,
      origin: "invite_card",
    });
  });

  it("ledger pulls carry NO origin (byte-identical to the pre-BUG2 frame)", () => {
    expect(ledgerInvite(7)).toEqual({ type: "roster_invite", spawn_id: 7 });
    expect("origin" in ledgerInvite(7)).toBe(false);
  });
});

describe("App wires every roster_invite through the builders", () => {
  // vitest runs with cwd = web/
  const appSource = readFileSync(resolve(process.cwd(), "src/App.tsx"), "utf-8");

  it("constructs no roster_invite frame inline", () => {
    expect(appSource).not.toContain("type: 'roster_invite'");
    expect(appSource).not.toContain('type: "roster_invite"');
  });

  it("uses the card builder for BOTH card surfaces (invite card + staffing picker)", () => {
    const cardUses = appSource.match(/wsSend\(cardAcceptInvite\(/g) ?? [];
    expect(cardUses).toHaveLength(2);
  });

  it("keeps the Ledger surfaces on the origin-free builder", () => {
    const ledgerUses = appSource.match(/wsSend\(ledgerInvite\(/g) ?? [];
    expect(ledgerUses).toHaveLength(2);
  });
});
