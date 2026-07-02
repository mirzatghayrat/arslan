/**
 * mention-chips.test.tsx — routing announcement @-mention chips + store handling.
 *
 * (a) MentionText: known @SpawnName tokens become accent chips; unknown @text stays plain.
 * (b) store: a routing frame carrying `announcement` appends a route-announcement item;
 *     a plain routing frame appends nothing (unchanged behavior).
 * (c) auto_continue frame keeps the thinking indicator alive (the UI pulse continues
 *     while the backend automatically re-dispatches after a digest round).
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import MentionText, { renderMentions } from "../components/MentionText";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

// ---------------------------------------------------------------------------
// MentionText tokenizer
// ---------------------------------------------------------------------------
describe("MentionText — @-mention chips", () => {
  it("wraps a known @spawn name (with spaces) in a mention chip", () => {
    render(
      <MentionText
        text={"@Deck Master — 可能接力:演示文稿"}
        knownNames={["Deck Master", "调研员"]}
      />,
    );
    const chip = screen.getByTestId("mention-chip");
    expect(chip.textContent).toBe("@Deck Master");
  });

  it("leaves unknown @text plain (mentions grounded in real names only)", () => {
    render(<MentionText text={"@Nobody — hi"} knownNames={["Deck Master"]} />);
    expect(screen.queryByTestId("mention-chip")).toBeNull();
    expect(screen.getByText(/@Nobody — hi/)).toBeTruthy();
  });

  it("multi-line announcement: one chip per known mention, unknown stays plain", () => {
    render(
      <MentionText
        text={"用户需要OKX调研并生成PPT\n@调研员 — 负责:市场调研\n@Unknown Guy — 可能接力"}
        knownNames={["调研员"]}
      />,
    );
    const chips = screen.getAllByTestId("mention-chip");
    expect(chips).toHaveLength(1);
    expect(chips[0].textContent).toBe("@调研员");
  });

  it("no known names → text passes through untouched", () => {
    const parts = renderMentions("@X plain text", []);
    expect(parts).toEqual(["@X plain text"]);
  });
});

// ---------------------------------------------------------------------------
// Store: routing announcement item + auto_continue thinking bridge
// ---------------------------------------------------------------------------
describe("arslanStore — routing announcement + auto_continue", () => {
  beforeEach(() => {
    useArslanStore.setState(initialArslanState(), true);
  });

  it("routing frame WITH announcement appends a route-announcement item", () => {
    useArslanStore.getState().handleFrame({
      type: "routing",
      spawn_id: 7,
      spawn_name: "调研员",
      announcement: "用户需要OKX调研\n@调研员 — 负责:市场调研",
    } as any);
    const s = useArslanStore.getState();
    expect(s.items).toHaveLength(1);
    expect(s.items[0].isRouteAnnouncement).toBe(true);
    expect(s.items[0].content).toContain("@调研员");
    expect(s.pendingRoute).toEqual({ spawnId: 7, spawnName: "调研员" });
  });

  it("routing frame WITHOUT announcement appends nothing (unchanged)", () => {
    useArslanStore.getState().handleFrame({
      type: "routing", spawn_id: 7, spawn_name: "调研员",
    } as any);
    expect(useArslanStore.getState().items).toHaveLength(0);
  });

  it("auto_continue keeps the thinking indicator alive", () => {
    useArslanStore.getState().handleFrame({ type: "auto_continue", spawn_id: 7 } as any);
    const s = useArslanStore.getState();
    expect(s.thinking).toBe(true);
    expect(s.workStartedAt).not.toBeNull();
  });
});
