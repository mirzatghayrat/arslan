import { beforeEach, expect, it } from "vitest";
import { EXPERT_CHATS_KEY, restoreExpertChats, saveExpertChats } from "../lib/expertChats";
beforeEach(() => localStorage.clear());
it("stores only explicitly opened expert identities and preserves recency order", () => {
  saveExpertChats(["9", "2"]);
  expect(restoreExpertChats()).toEqual(["9", "2"]);
});
it("ignores malformed identities and duplicate entries", () => {
  localStorage.setItem(EXPERT_CHATS_KEY, JSON.stringify(["2", "2", "https://example.com", {}, "-1"]));
  expect(restoreExpertChats()).toEqual(["2"]);
});
