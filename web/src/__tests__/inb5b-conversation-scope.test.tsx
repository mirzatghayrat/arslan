/** INB5b (v0.1.64), #602 review findings 4 and 5. What App draws for a conversation, tested as it is composed: the ask slot and the
 *  conversation's two pieces in ONE answer guard (without it the slot and the away list each keep their own, and a double-click on Run
 *  lands on "Always allow"), and a temporary conversation with neither piece. And a conversation asks the server only for its own: the
 *  URLs name it, and an empty id is sent rather than dropped, so the server refuses it instead of listing every conversation's. */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k), i18n: { language: "en" } }),
}));

import * as client from "../api/client";
import { proactiveApi } from "../api/proactive";
import ConversationStage from "../components/conversation/ConversationStage";
import { AwayEntries } from "../components/conversation/WhileAway";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => {
  useArslanStore.setState(initialArslanState(), true);
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-01T10:00:00Z"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
const settle = async (ms = 0) => { for (let t = 0; t < ms; t += 50) await act(async () => { await vi.advanceTimersByTimeAsync(Math.min(50, ms - t)); });
  await act(async () => { await vi.advanceTimersByTimeAsync(0); }); };
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const cmd = (id: string, pretty: string) => ({ type: "propose_run_command", call_id: id, pretty, reason: "",
  options: ["once", "conversation", "always"], always_label: "that command", perm_kind: "command" });
const row = (id: number, detail: string) => ({ id, created_at: "2026-11-01T09:00:00Z", first_at: "2026-11-01T09:00:00Z", count: 1, conversation_id: "c",
  kind: "command", target: `rules:${id}`, detail, always_ok: true, always: [{ kind: "legacy_rule", target: "send-mail", label: "sends email" }],
  unattended: false });
const job = (id: number) => ({ id, kind: "job_followup", title_key: "title.job_followup", params: { goal: "x" }, evidence: [],
  goal: "Finish the report.", priority: "normal", status: "new", diagnosis: null, conversation_id: "c", job_id: "j1",
  created_at: "2026-11-01T09:00:00", snooze_until: null });

function serve(refused: unknown[] = [], jobs: unknown[] = []) {
  const calls: string[] = [];
  vi.spyOn(client, "request").mockImplementation((async (path: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${path}`);
    if (path.startsWith("/approvals/refused")) return refused;
    if (path === "/permissions/rules") return { rules: [{ id: 99 }] };
    if (path.startsWith("/proactive/items?")) return { items: jobs };
    return { ok: true };
  }) as never);
  return calls;
}
const stage = (send: (frame: Record<string, unknown>) => void, temporary = false) =>
  <ConversationStage send={send} conversationId="c" temporary={temporary} onOpenConversation={vi.fn()} onOpenModelSettings={vi.fn()}>
    {({ header, footer }) => <div>{header}<p>the messages</p>{footer}</div>}
  </ConversationStage>;

describe("what App draws for a conversation", () => {
  it("puts the slot and the conversation in one guard: a double-click on Run is not an 「Always allow」 on the entry under it", async () => {
    const calls = serve([row(7, "mail -s hi me@x.com")]);
    const send = vi.fn();
    render(stage(send));
    frame(cmd("a", "echo harmless"));
    await settle(600);
    fireEvent.click(screen.getByTestId("runcmd-run"));               // click 1 answers the card, which leaves the slot
    expect(send).toHaveBeenCalledWith({ type: "confirm_run_command", call_id: "a", scope: "once" });
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));      // click 2, on the entry now under the pointer
    await settle();
    expect(calls).not.toContain("POST /permissions/rules");
  });

  it("shows what was not done and the stopped jobs in an ordinary conversation, and neither in a temporary one", async () => {
    const calls = serve([row(7, "mail -s hi me@x.com")], [job(5)]);
    const { unmount } = render(stage(vi.fn()));
    await settle();
    expect(screen.getByTestId("inbox-refused")).toBeTruthy();
    expect(screen.getByText("proactive.item.doIt")).toBeTruthy();
    unmount();
    calls.length = 0;
    render(stage(vi.fn(), true));
    await settle();
    expect(screen.getByText("the messages")).toBeTruthy();
    expect(screen.queryByTestId("inbox-refused")).toBeNull();
    expect(screen.queryByText("proactive.item.doIt")).toBeNull();
    expect(calls.filter((c) => c.includes("/approvals/refused") || c.includes("/proactive/items"))).toEqual([]);
  });
});

describe("a conversation asks only for its own", () => {
  it("names the conversation and the kind in the items URL", async () => {
    const calls = serve();
    await proactiveApi.items("all", { conversationId: "c1", kind: "job_followup" });
    expect(calls).toEqual(["GET /proactive/items?scope=all&conversation_id=c1&kind=job_followup"]);
  });

  it("sends an empty id rather than dropping it, so the server refuses it instead of listing every conversation's", async () => {
    const calls = serve();
    await proactiveApi.items("all", { conversationId: "", kind: "job_followup" });
    expect(calls).toEqual(["GET /proactive/items?scope=all&conversation_id=&kind=job_followup"]);
    render(<AwayEntries conversationId="" />);
    await settle();
    expect(calls).toContain("GET /approvals/refused?hours=24&conversation_id=");
  });
});
