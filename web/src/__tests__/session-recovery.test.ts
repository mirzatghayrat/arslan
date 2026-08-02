/**
 * Gate item ⑦ — conversations must come back from the SERVER, not localStorage.
 *
 * localStorage was the only record of which conversations existed, and in the
 * packaged app it is wiped on every launch (ephemeral sidecar port → new
 * origin → fresh partition). The rows were never lost; nothing could name them.
 * `mergeServerConversations` is the recovery: the server supplies the SET,
 * localStorage supplies titles the user has seen before.
 */
import { describe, it, expect } from "vitest";

import { mergeServerConversations } from "../lib/sessionPersistence";

const stored = [
  { id: "thread-100", title: "Renamed by the user", history: [] as [] },
];
const server = [
  { conversation_id: "thread-100", title: "raw opening line", message_count: 9, last_at: "2026-08-01T10:00:00" },
  { conversation_id: "thread-999", title: "chart the payment platforms", message_count: 74, last_at: "2026-08-01T16:00:00" },
];

describe("mergeServerConversations", () => {
  it("recovers a conversation localStorage has never heard of", () => {
    const out = mergeServerConversations(stored, server);
    expect(out.map((t) => t.id)).toContain("thread-999");
    expect(out.find((t) => t.id === "thread-999")?.title).toBe("chart the payment platforms");
  });

  it("keeps the title the user already knows", () => {
    // Discriminating: taking the server title unconditionally would silently
    // rename every thread the user has open the first time this ships.
    const out = mergeServerConversations(stored, server);
    expect(out.find((t) => t.id === "thread-100")?.title).toBe("Renamed by the user");
  });

  it("never drops a stored thread the server has not seen", () => {
    // A brand-new thread has no messages yet, so it is absent server-side. If
    // the server list simply replaced the local one, starting a new session and
    // reloading before typing would delete it.
    const out = mergeServerConversations(
      [...stored, { id: "thread-brand-new", title: "New Session", history: [] as [] }],
      server,
    );
    expect(out.map((t) => t.id)).toContain("thread-brand-new");
  });

  it("orders most recently active first, with unseen threads kept at the front", () => {
    const out = mergeServerConversations(
      [{ id: "thread-brand-new", title: "New Session", history: [] as [] }],
      server,
    );
    expect(out[0].id).toBe("thread-brand-new");
    expect(out.slice(1).map((t) => t.id)).toEqual(["thread-999", "thread-100"]);
  });

  it("never blanks the history of a thread already in memory", () => {
    // Caught by the TYPE CHECKER first, and it is a real defect, not a typing
    // nuisance: the merge rebuilt every server-known thread with `history: []`,
    // so the conversation the user was looking at would have gone blank the
    // moment recovery ran.
    const live = [{ id: "thread-100", title: "Renamed by the user",
                    history: [{ id: 1, role: "user", content: "hi" }] }];
    const out = mergeServerConversations(live, server);
    const kept = out.find((t) => t.id === "thread-100") as typeof live[0];
    expect(kept.history).toHaveLength(1);
  });

  it("an unreachable server leaves the local list exactly as it was", () => {
    // Fail-open: a backend that has not finished booting must not look like
    // "you have no conversations".
    expect(mergeServerConversations(stored, [])).toEqual(stored);
  });
});
