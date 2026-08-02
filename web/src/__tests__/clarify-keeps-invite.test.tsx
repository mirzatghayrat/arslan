/**
 * A clarify answer is not "the user moved on".
 *
 * `sendOrchestratorMessage` opens with `dismissAllPending()` (App.tsx), and its
 * comment gives the reason: a user who types a new message without acting on a
 * pending proposal card has implicitly declined it, so cards clear instead of
 * stacking forever. That reasoning is right for a TYPED message.
 *
 * Picking a clarify option also goes through that function
 * (OrchestratorChat.tsx: markClarifyAnswered -> onSendMessage(label)), so
 * answering Arslan's own question destroyed the spawn invite sitting beside it.
 * The two were mutually exclusive by construction — the user reported having to
 * choose one, and answering the question is the most engaged moment there is,
 * the opposite of moving on.
 */
import { describe, it, expect, beforeEach } from "vitest";

import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { useArslanStore } from "../stores/arslanStore";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OrchestratorChatSource = readFileSync(resolve(SRC, "components/OrchestratorChat.tsx"), "utf8");
const AppSource = readFileSync(resolve(SRC, "App.tsx"), "utf8");

const invite = { spawnId: 7, reason: "Let Data & Chart Analyst take this?" };

beforeEach(() => {
  useArslanStore.setState({
    pendingInvite: null, suggestion: null, pendingStaffing: null, pendingUpdate: null,
    items: [],
  } as never);
});

describe("clarify answers vs pending cards", () => {
  it("a typed message still clears an un-acted invite", () => {
    // The behaviour that must SURVIVE: this is what stops cards stacking.
    useArslanStore.setState({ pendingInvite: invite } as never);
    useArslanStore.getState().dismissAllPending();
    expect(useArslanStore.getState().pendingInvite).toBeNull();
  });

  it("a plain send applies the implicit decline", () => {
    useArslanStore.setState({ pendingInvite: invite } as never);
    useArslanStore.getState().noteUserSend();
    expect(useArslanStore.getState().pendingInvite).toBeNull();
  });

  it("a clarify answer does NOT", () => {
    useArslanStore.setState({ pendingInvite: invite } as never);
    useArslanStore.getState().noteUserSend({ fromClarify: true });
    expect(useArslanStore.getState().pendingInvite).toEqual(invite);
  });

  it("the clarify pick actually passes the flag", () => {
    // The first version of this file asserted on `addUserMessage`, which never
    // dismissed anything — so all three tests passed before a line of the fix
    // existed. The rule lives in the store; the CALL SITE has to reach it.
    const src = OrchestratorChatSource;
    expect(src).toContain("fromClarify: true");
    expect(src).toMatch(/onSendMessage\?\.\(label, undefined, \{ fromClarify: true \}\)/);
  });

  it("the send path routes through noteUserSend, not the bare dismissal", () => {
    expect(AppSource).toContain("noteUserSend(opts)");
    expect(AppSource).not.toMatch(/dismissAllPending\(\);\n\s*useArslanStore\.getState\(\)\.addUserMessage/);
  });
});
