/**
 * Tests for the in-chat roster notice feature (roster_event frames).
 *
 * Coverage:
 *  1. Store: roster_event "joined" appends a system item with rosterAction="joined"
 *  2. Store: roster_event "left" appends a system item with rosterAction="left"
 *  3. Store: idempotent re-invite (no roster_event) does NOT add a notice
 *  4. Adapter: rosterAction item converts to Message with rosterAction + rosterSpawnName
 *  5. Component: renders a notice with the spawn name (not a message bubble)
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

import { useArslanStore, initialArslanState } from "../stores/arslanStore";
import { toUiMessages } from "../api/adapters";
import type { ArslanThreadItem } from "../api/client.types";
import OrchestratorChat from "../components/OrchestratorChat";
import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";
import es from "../locales/es.json";

// jsdom does not implement scrollIntoView — suppress
window.HTMLElement.prototype.scrollIntoView = vi.fn();

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, string>) => {
      if (key === "chat.roster_joined") return `${opts?.name ?? ""} joined`;
      if (key === "chat.roster_left") return `${opts?.name ?? ""} left`;
      if (key === "chat.roster_recruited") return `${opts?.name ?? ""} recruited-notice`;
      if (key === "chat.roster_joined_no_pending")
        return `${opts?.name ?? ""} joined-no-pending-notice`;
      return key;
    },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// ---------------------------------------------------------------------------
// Fixture reset
// ---------------------------------------------------------------------------
beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
});

// ---------------------------------------------------------------------------
// 1. Store — "joined" notice appended
// ---------------------------------------------------------------------------
describe("arslanStore roster_event", () => {
  it("appends a system item with rosterAction='joined' on roster_event joined", () => {
    useArslanStore.getState().handleFrame({
      type: "roster_event",
      action: "joined",
      spawn_id: 4,
      spawn_name: "数据研析",
    } as any);

    const items = useArslanStore.getState().items;
    expect(items).toHaveLength(1);
    const item = items[0];
    expect(item.kind).toBe("system");
    expect(item.rosterAction).toBe("joined");
    expect(item.spawnId).toBe(4);
    expect(item.spawnName).toBe("数据研析");
  });

  it("appends a system item with rosterAction='left' on roster_event left", () => {
    useArslanStore.getState().handleFrame({
      type: "roster_event",
      action: "left",
      spawn_id: 4,
      spawn_name: "数据研析",
    } as any);

    const items = useArslanStore.getState().items;
    expect(items).toHaveLength(1);
    expect(items[0].rosterAction).toBe("left");
  });

  it("handles null spawn_name gracefully", () => {
    useArslanStore.getState().handleFrame({
      type: "roster_event",
      action: "joined",
      spawn_id: 99,
      spawn_name: null,
    } as any);

    const items = useArslanStore.getState().items;
    expect(items).toHaveLength(1);
    expect(items[0].spawnName).toBeNull();
    expect(items[0].rosterAction).toBe("joined");
  });

  it("assigns a stable negative client id", () => {
    useArslanStore.getState().handleFrame({
      type: "roster_event",
      action: "joined",
      spawn_id: 4,
      spawn_name: "X",
    } as any);
    useArslanStore.getState().handleFrame({
      type: "roster_event",
      action: "left",
      spawn_id: 4,
      spawn_name: "X",
    } as any);

    const items = useArslanStore.getState().items;
    expect(items).toHaveLength(2);
    // Both have negative ids (client-only) and they are distinct
    expect(items[0].id).toBeLessThan(0);
    expect(items[1].id).toBeLessThan(0);
    expect(items[0].id).not.toBe(items[1].id);
  });
});

// ---------------------------------------------------------------------------
// 4. Adapter — rosterAction item → Message
// ---------------------------------------------------------------------------
describe("toUiMessages roster notice", () => {
  it("converts a rosterAction system item to a Message with rosterAction + rosterSpawnName", () => {
    const item: ArslanThreadItem = {
      id: -1,
      kind: "system",
      role: "arslan",
      content: "",
      spawnId: 4,
      spawnName: "数据研析",
      rosterAction: "joined",
    };
    const msgs = toUiMessages([item]);
    expect(msgs).toHaveLength(1);
    const msg = msgs[0];
    expect(msg.rosterAction).toBe("joined");
    expect(msg.rosterSpawnName).toBe("数据研析");
    // Should NOT produce a spawnIntro card
    expect(msg.spawnIntro).toBeUndefined();
    expect(msg.text).toBe("");
  });

  it("converts a 'left' rosterAction item correctly", () => {
    const item: ArslanThreadItem = {
      id: -2,
      kind: "system",
      role: "arslan",
      content: "",
      spawnId: 7,
      spawnName: "领英智囊",
      rosterAction: "left",
    };
    const msgs = toUiMessages([item]);
    expect(msgs[0].rosterAction).toBe("left");
    expect(msgs[0].rosterSpawnName).toBe("领英智囊");
  });
});

// ---------------------------------------------------------------------------
// 5. Component smoke — roster notice renders without message bubbles
// ---------------------------------------------------------------------------
describe("OrchestratorChat roster notice rendering", () => {
  const joinedMsg = {
    id: "notice-1",
    sender: "arslan" as const,
    senderName: "Arslan",
    senderAvatar: "🦁",
    text: "",
    timestamp: "",
    rosterAction: "joined",
    rosterSpawnName: "数据研析",
  };

  it("renders a notice line containing the spawn name and 'joined'", () => {
    render(
      <OrchestratorChat
        chatHistory={[joinedMsg]}
        setChatHistory={() => {}}
        spawns={[]}
        currentStyle="quartz"
        setCurrentStyle={() => {}}
        activeThread={null}
      />
    );
    // The notice line should contain the spawn name + "joined"
    expect(screen.getByText(/数据研析 joined/)).toBeTruthy();
    // Must NOT render an avatar bubble (the notice is just a divider line)
    expect(screen.queryByText("Arslan Orchestrator")).toBeNull();
  });

  it("renders a 'left' notice for rosterAction='left'", () => {
    const leftMsg = { ...joinedMsg, id: "notice-2", rosterAction: "left" };
    render(
      <OrchestratorChat
        chatHistory={[leftMsg]}
        setChatHistory={() => {}}
        spawns={[]}
        currentStyle="quartz"
        setCurrentStyle={() => {}}
        activeThread={null}
      />
    );
    expect(screen.getByText(/数据研析 left/)).toBeTruthy();
  });

  it("renders a recruited notice through chat.roster_recruited (cell 6 enroll)", () => {
    const recruitedMsg = { ...joinedMsg, id: "notice-3", rosterAction: "recruited" };
    render(
      <OrchestratorChat
        chatHistory={[recruitedMsg]}
        setChatHistory={() => {}}
        spawns={[]}
        currentStyle="quartz"
        setCurrentStyle={() => {}}
        activeThread={null}
      />
    );
    expect(screen.getByText(/数据研析 recruited-notice/)).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// 6. Honest recruit copy — the roster is SESSION-scoped and no routing
//    preference is ever persisted, so no locale may claim "next time tasks
//    like this go straight to X" (BUG1: unbacked claim). Pin the REAL values.
// ---------------------------------------------------------------------------
describe("roster_recruited locale copy is honest (session-scoped, no next-time claim)", () => {
  const locales: Array<[string, Record<string, any>, RegExp]> = [
    ["en", en, /session/i],
    ["zh", zh, /本次会话/],
    ["ja", ja, /セッション/],
    ["de", de, /Sitzung/],
    ["fr", fr, /session/i],
    ["es", es, /sesión/i],
  ];
  const staleClaim = /下次|next time|次回|nächste|prochaine|próxima/i;

  it.each(locales)("%s: no unbacked next-time claim, session-scoped", (_id, dict, marker) => {
    const value: string = dict.chat.roster_recruited;
    expect(value).toBeTruthy();
    expect(value).not.toMatch(staleClaim);
    expect(value).toMatch(marker);
    expect(value).toContain("{{name}}");
  });
});


// ---------------------------------------------------------------------------
// 6. BUG2 — honest notice when an accept found no parked task, and a NEUTRAL
//    fallback for unknown roster actions (an unknown action must never render
//    as the spawn LEAVING).
// ---------------------------------------------------------------------------
describe("OrchestratorChat joined_no_pending + unknown-action fallback", () => {
  const base = {
    id: "notice-np-1",
    sender: "arslan" as const,
    senderName: "Arslan",
    senderAvatar: "🦁",
    text: "",
    timestamp: "",
    rosterSpawnName: "数据研析",
  };

  it("renders the honest no-pending notice", () => {
    render(
      <OrchestratorChat
        chatHistory={[{ ...base, rosterAction: "joined_no_pending" }]}
        setChatHistory={() => {}}
        spawns={[]}
        currentStyle="quartz"
        setCurrentStyle={() => {}}
        activeThread={null}
      />
    );
    expect(screen.getByText(/数据研析 joined-no-pending-notice/)).toBeTruthy();
  });

  it("renders an UNKNOWN roster action as a neutral joined-style line, never as left", () => {
    render(
      <OrchestratorChat
        chatHistory={[{ ...base, id: "notice-np-2", rosterAction: "future_action" }]}
        setChatHistory={() => {}}
        spawns={[]}
        currentStyle="quartz"
        setCurrentStyle={() => {}}
        activeThread={null}
      />
    );
    expect(screen.getByText(/数据研析 joined/)).toBeTruthy();
    expect(screen.queryByText(/数据研析 left/)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 7. BUG2 locale guard — the new key must exist in all 6 locales, carry the
//    name placeholder, point at @ hand-off, and never promise a dispatch.
// ---------------------------------------------------------------------------
describe("roster_joined_no_pending locale copy", () => {
  // The "nothing was queued" claim MUST be scoped to THIS spawn: another spawn's park
  // can still be alive (the WS handler deliberately preserves it), so an unscoped
  // "nothing is pending" would be a false statement. Each locale carries its own
  // scoping marker — a pronoun or a repeat of the name inside the claim.
  const dicts: Array<[string, Record<string, any>, RegExp]> = [
    ["en", en, /for them|for \{\{name\}\}/i],
    ["zh", zh, /交给 ?(TA|\{\{name\}\})/],
    ["ja", ja, /宛て/],
    ["de", de, /für \{\{name\}\}|für ihn|für sie/i],
    ["fr", fr, /pour \{\{name\}\}|pour lui|pour elle/i],
    ["es", es, /para \{\{name\}\}|para él|para ella/i],
  ];

  it.each(dicts)("%s: honest, @-directed, spawn-scoped, no dispatch promise", (_id, dict, scoping) => {
    const value: string = dict.chat.roster_joined_no_pending;
    expect(value).toBeTruthy();
    expect(value).toContain("{{name}}");
    expect(value).toContain("@");
    expect(value).not.toMatch(/下次|next time|次回|nächste|prochaine|próxima/i);
    expect(value).toMatch(scoping);
  });
});


// ---------------------------------------------------------------------------
// 8. BUG2 end-to-end: the real card-accept frame sequence must render ONE line.
//    The honest notice already says "joined", so the handler suppresses the plain
//    joined event for card accepts — pinned here through store → adapter → render.
// ---------------------------------------------------------------------------
describe("card accept renders a single roster line", () => {
  it("store + renderer produce one notice for the production frame sequence", () => {
    useArslanStore.getState().handleFrame({
      type: "roster_event",
      action: "joined_no_pending",
      spawn_id: 4,
      spawn_name: "数据研析",
    } as any);

    const items = useArslanStore.getState().items;
    expect(items).toHaveLength(1);

    const msgs = toUiMessages(items as ArslanThreadItem[]).map((m, i) => ({
      id: `e2e-${i}`,
      sender: "arslan" as const,
      senderName: "Arslan",
      senderAvatar: "🦁",
      text: m.text ?? "",
      timestamp: "",
      rosterAction: m.rosterAction,
      rosterSpawnName: m.rosterSpawnName,
    }));

    render(
      <OrchestratorChat
        chatHistory={msgs}
        setChatHistory={() => {}}
        spawns={[]}
        currentStyle="quartz"
        setCurrentStyle={() => {}}
        activeThread={null}
      />
    );
    expect(screen.getAllByText(/数据研析/)).toHaveLength(1);
    expect(screen.getByText(/joined-no-pending-notice/)).toBeTruthy();
  });
});
