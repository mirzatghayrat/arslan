/** 0.1.61 §A4: whatever a card hands the slot, the slot puts only a scope its frame offered on the wire — the
 *  second wall behind each card's own check (the server checks a third time). The cards are stubs here, so the
 *  test can hand the slot what no real card would. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, act, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

type Handlers = { onConfirm: (...args: unknown[]) => void; onCancel: (...args: unknown[]) => void };
type ConnectProps = { callId: string; onApplied: (res: unknown) => void; onCancel: () => void; queue: { onNext?: () => void } };
const shown = vi.hoisted(() => ({} as Record<string, Handlers>));
const connect = vi.hoisted(() => ({} as { props?: ConnectProps }));
vi.mock("../components/RunCommandCard", () => ({ default: (p: Handlers) => { shown.run = p; return null; } }));
vi.mock("../components/WorkspaceWriteCard", () => ({ default: (p: Handlers) => { shown.write = p; return null; } }));
vi.mock("../components/ScheduleGrantCard", () => ({ default: (p: Handlers) => { shown.schedule = p; return null; } }));
vi.mock("../components/ActionApprovalCard", () => ({ default: (p: Handlers) => { shown.action = p; return null; } }));
vi.mock("../components/ConnectMcpCard", () => ({ default: (p: ConnectProps) => { connect.props = p; return null; } }));

import AskSlot from "../components/AskSlot";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));
afterEach(() => { cleanup(); for (const k of Object.keys(shown)) delete shown[k]; delete connect.props; });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });

// [card, its frame, the frame its yes answers, how that card says yes with a scope]
const CARDS: [string, Record<string, unknown>, string, (scope: string) => void][] = [
  ["the command card", { type: "propose_run_command", call_id: "k", pretty: "ls" }, "confirm_run_command",
    (scope) => shown.run.onConfirm("k", scope)],
  ["the write card", { type: "propose_workspace_write", call_id: "k", workspace: "/w", action: "write_file", path: "a" }, "confirm_workspace_write",
    (scope) => shown.write.onConfirm("k", scope)],
  ["the schedule card", { type: "propose_schedule", call_id: "k", name: "n", when: "every: 60" }, "confirm_schedule",
    (scope) => shown.schedule.onConfirm("k", scope)],
  ["the action card", { type: "propose_action", call_id: "k", kind: "app", target: "x", detail: "" }, "confirm_action",
    (scope) => shown.action.onConfirm(scope)],
];
const OFFER = { options: ["once", "conversation", "always"], always_label: "" };    // Always has no literal scope: it is not offered

describe("the slot sends only a scope the frame offered", () => {
  it.each(CARDS)("%s: a scope it offered goes out as it is", (_name, make, type, say) => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame({ ...make, ...OFFER });
    act(() => say("conversation"));
    expect(send.mock.calls).toStrictEqual([[{ type, call_id: "k", scope: "conversation" }]]);
  });

  it.each(CARDS)("%s: a scope the frame never listed, or Always with no literal scope, goes out as the first choice", (_name, make, type, say) => {
    for (const hostile of ["forever", "always", "  ", "ONCE"]) {
      const send = vi.fn();
      render(<AskSlot send={send} />);
      frame({ ...make, ...OFFER });
      act(() => say(hostile));
      expect(send.mock.calls, hostile).toStrictEqual([[{ type, call_id: "k", scope: "once" }]]);
      cleanup();
      useArslanStore.setState(initialArslanState(), true);
    }
  });
});

// ── The connect card: its answers are its own, by call id ───────────────────────────────────────────────

describe("a connect-MCP card answers for itself", () => {
  const CONNECT = (id: string) => ({ type: "propose_connect_mcp", call_id: id, key: "memory", label: "Memory", transport: "stdio", command: "npx",
    argv: [], url: null, env_keys: [], prerequisites: "", requires_path: false, path_placeholder: null });
  const OK = { ok: true, serverId: 7, toolCount: 3, safeCount: 3, restrictedCount: 0, assignable: true };

  it("a connect that worked sends the secret-free confirm with its own call id, and marks only that card with the server", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(CONNECT("m1"));
    frame(CONNECT("m2"));
    act(() => connect.props!.queue.onNext!());                       // page to the second card
    expect(connect.props!.callId).toBe("m2");
    act(() => connect.props!.onApplied(OK));
    expect(send.mock.calls).toStrictEqual([[{ type: "confirm_connect_mcp", call_id: "m2", server_id: 7, tool_count: 3 }]]);
    expect(useArslanStore.getState().pendingConnectMcps.map((c) => [c.callId, c.appliedServerId])).toEqual([["m1", undefined], ["m2", 7]]);
    // the server echoes the confirm's call id in the follow-up: it names the card, and the card closes by it
    frame({ type: "mcp_connect_followup", call_id: "m2", server_id: 7, tool_count: 3, safe_count: 3, restricted_count: 0, assignable: true });
    expect(useArslanStore.getState().pendingConnectMcps.map((c) => c.callId)).toEqual(["m1"]);
  });

  it("a follow-up from a server that names no card still closes the card that connected the server", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(CONNECT("m1"));
    frame(CONNECT("m2"));
    act(() => connect.props!.queue.onNext!());
    act(() => connect.props!.onApplied(OK));
    frame({ type: "mcp_connect_followup", server_id: 7, tool_count: 3, safe_count: 3, restricted_count: 0, assignable: true });
    expect(useArslanStore.getState().pendingConnectMcps.map((c) => c.callId)).toEqual(["m1"]);
  });

  it("a connect that failed sends nothing and marks nothing; the card stays for another try", () => {
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(CONNECT("m1"));
    act(() => connect.props!.onApplied({ ok: false, stage: "add", message: "no" }));
    expect(send).not.toHaveBeenCalled();
    expect(useArslanStore.getState().pendingConnectMcps[0]).not.toHaveProperty("appliedServerId");
  });

  it("cancelling takes out the card shown and no other", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(CONNECT("m1"));
    frame(CONNECT("m2"));
    act(() => connect.props!.onCancel());
    expect(useArslanStore.getState().pendingConnectMcps.map((c) => c.callId)).toEqual(["m2"]);
  });
});
