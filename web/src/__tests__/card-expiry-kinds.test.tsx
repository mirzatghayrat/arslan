/** 0.1.61 §A4 (review of PR 2b Task 3): a card of EVERY kind the chat slot holds runs out the same way — it leaves 2 s after its
 *  expiry and the slot says it is waiting for you; the server's `card_resolved: expired` says the same; a re-sent card's later
 *  expiry replaces the old one. card-v2.test.tsx pins this for the command and write cards only. Fix round 1 (R5): the
 *  enroll-node and connect-MCP cards are in the table too — they used to sit at 0:00 for good. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import AskSlot from "../components/AskSlot";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => { useArslanStore.setState(initialArslanState(), true); vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-13T10:00:00Z")); });
afterEach(() => { cleanup(); vi.useRealTimers(); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });
const inSeconds = (s: number) => Date.now() / 1000 + s;

const CAPABILITY = { type: "propose_capability", call_id: "k1", kind: "mcp", name: "excel-mcp-server", summary: "Reads .xlsx",
  source_url: "https://github.com/a/b", repo: "a/b", version: "1.1.2", license: { spdx: "MIT", read_from: "github:LICENSE" }, stars: 1,
  pushed_days: 10, runtime: "uv", runtime_download: null, remote_host: null, network: false, folders: [], keys: [], why: "w", retry: "r" };

const ENROLL = { type: "propose_enroll_node", call_id: "n1", name: "mini", host: "10.0.0.2", user: "me", fingerprints: ["SHA256:abc"] };
const CONNECT = { type: "propose_connect_mcp", call_id: "m1", key: "memory", label: "Memory", transport: "stdio", command: "npx", argv: [],
  url: null, env_keys: [], prerequisites: "", requires_path: false, path_placeholder: null };

// [name, the card's frame (with an optional expiry), its test id]
const KINDS: [string, (expires?: number) => Record<string, unknown>, string][] = [
  ["a command card", (e) => ({ type: "propose_run_command", call_id: "c1", pretty: "ls", reason: "", options: ["once", "conversation"], ...(e ? { expires_at: e } : {}) }), "runcmd-card"],
  ["a write card", (e) => ({ type: "propose_workspace_write", call_id: "w1", workspace: "/w", action: "write_file", path: "a", options: ["once", "conversation"], ...(e ? { expires_at: e } : {}) }), "wswrite-card"],
  ["a schedule card", (e) => ({ type: "propose_schedule", call_id: "s1", name: "n", when: "every: 60", options: ["once", "conversation"], ...(e ? { expires_at: e } : {}) }), "schedule-card"],
  ["an action card", (e) => ({ type: "propose_action", call_id: "a1", kind: "app", target: "x", detail: "", title: "Use x?", options: ["task", "conversation"], ...(e ? { expires_at: e } : {}) }), "action-card"],
  ["a capability card", () => CAPABILITY, "capability-card"],
  ["an enroll-node card", () => ENROLL, "enroll-node-card"],
  ["a connect-MCP card", () => CONNECT, "connect-mcp-card"],
];
const IDS: Record<string, string> = { "runcmd-card": "c1", "wswrite-card": "w1", "schedule-card": "s1", "action-card": "a1", "capability-card": "k1",
  "enroll-node-card": "n1", "connect-mcp-card": "m1" };

describe("a card of every kind runs out", () => {
  it.each(KINDS)("%s leaves 2 s after its expiry (30 minutes after it arrived, when the frame says no time) and the slot says it is waiting for you", (_n, make, id) => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(make(inSeconds(1800)));
    advance(1_800_000);
    expect(screen.getByTestId(id)).toBeInTheDocument();              // the server closes it first
    advance(2_000);
    expect(screen.queryByTestId(id)).toBeNull();
    expect(screen.getByTestId("ask-expired")).toBeInTheDocument();
    expect(send).not.toHaveBeenCalled();
    cleanup();
    useArslanStore.setState(initialArslanState(), true);
    render(<AskSlot send={send} />);
    frame(make());                                                     // no expires_at: arrival + 30 minutes
    advance(1_801_000);
    expect(screen.getByTestId(id)).toBeInTheDocument();
    advance(1_100);
    expect(screen.queryByTestId(id)).toBeNull();
    expect(screen.getByTestId("ask-expired")).toBeInTheDocument();
  });

  it.each(KINDS)("%s closed by the server as expired says the same; the id decides which card", (_n, make, id) => {
    render(<AskSlot send={vi.fn()} />);
    frame(make(inSeconds(1800)));
    frame({ type: "card_resolved", call_id: "not-this-one", outcome: "expired" });
    expect(screen.getByTestId(id)).toBeInTheDocument();
    expect(screen.queryByTestId("ask-expired")).toBeNull();
    frame({ type: "card_resolved", call_id: IDS[id], outcome: "expired" });
    expect(screen.queryByTestId(id)).toBeNull();
    expect(screen.getByTestId("ask-expired")).toBeInTheDocument();
  });

  it.each(KINDS)("expireCard closes %s and nothing else", (_n, make, id) => {
    render(<AskSlot send={vi.fn()} />);
    frame(make(inSeconds(1800)));
    act(() => { useArslanStore.getState().expireCard(IDS[id]); });
    expect(screen.queryByTestId(id)).toBeNull();
    expect(useArslanStore.getState().cardExpired).toBe(true);
  });
});

describe("a card whose time moves", () => {
  it("a plain card sent again later (a reload restarts its countdown) is not closed by the first timer", () => {
    render(<AskSlot send={vi.fn()} />);
    const plain = { type: "propose_run_command", call_id: "p1", pretty: "ls", reason: "", sandbox: "outside", why: "w" };
    frame(plain);
    advance(1_000_000);
    frame(plain);                                                      // a new arrival: it counts 30 minutes from now
    advance(900_000);                                                  // 1 900 s after the first arrival: the first timer's moment has gone
    expect(screen.getByTestId("runcmd-card")).toBeInTheDocument();
    advance(902_000);                                                  // 30 min + 2 s after the second (at 2 802 s)
    expect(screen.queryByTestId("runcmd-card")).toBeNull();
    expect(screen.getByTestId("ask-expired")).toBeInTheDocument();
  });

  it("two cards that run out at the same moment both leave", () => {
    render(<AskSlot send={vi.fn()} />);
    const at = inSeconds(60);
    frame({ type: "propose_run_command", call_id: "c1", pretty: "ls", reason: "", options: ["once", "conversation"], expires_at: at });
    frame({ type: "propose_workspace_write", call_id: "w1", workspace: "/w", action: "write_file", path: "a", options: ["once", "conversation"], expires_at: at });
    advance(62_000);
    advance(10);                                                       // the next card to run out is timed once the first has left
    expect(useArslanStore.getState().pendingCommands).toEqual([]);
    expect(useArslanStore.getState().pendingWorkspaceWrites).toEqual([]);
    expect(screen.getByTestId("ask-expired")).toBeInTheDocument();
  });
});
