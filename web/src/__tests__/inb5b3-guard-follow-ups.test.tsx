/** INB5b-3 (v0.1.64), from ④参谋's #602 re-check (comment 6548264092). A stopped job's card sits at the end of the conversation, so a
 *  reply streaming in scrolls it under a still pointer, as it does the away entries on top: its doors take the same local scroll hold.
 *  A click a hold ignores is no longer silent: the buttons look held while it lasts. And the parts of the stopped cards' hold that
 *  nothing pinned: a notice appearing, and a card changing state, hold the slot's card; Undo, like "Always allow", waits out a scroll. */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k), i18n: { language: "en" } }),
}));

import * as client from "../api/client";
import AskSlot from "../components/AskSlot";
import { StoppedJobCards } from "../components/conversation/WhileAway";
import { AnswerGuardScope, makeAnswerGuard } from "../components/kit/guard";
import NotDoneList from "../components/proactive/NotDoneList";
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
const cmd = (id: string) => ({ type: "propose_run_command", call_id: id, pretty: "echo harmless", reason: "",
  options: ["once", "conversation", "always"], always_label: "that command", perm_kind: "command" });
const job = (id: number, status = "new") => ({ id, kind: "job_followup", title_key: "title.job_followup", params: { goal: "x" }, evidence: [],
  goal: "Finish the report.", priority: "normal", status, diagnosis: null, conversation_id: "c", job_id: "j1",
  created_at: "2026-11-01T09:00:00", snooze_until: null });
const row = (id: number) => ({ id, created_at: "2026-11-01T09:00:00Z", first_at: "2026-11-01T09:00:00Z", count: 1, conversation_id: "c",
  kind: "command", target: `rules:${id}`, detail: "mail -s hi me@x.com", always_ok: true,
  always: [{ kind: "legacy_rule", target: "send-mail", label: "sends email" }], unattended: false });

/** A server with `jobs` stopped in the conversation and `refused` away entries; `accept` answers "Do it". */
function serve({ jobs = [] as unknown[] | (() => unknown[]), refused = [] as unknown[], accept = async (): Promise<unknown> => ({ job_id: "j2", conversation_id: "c" }) } = {}) {
  const calls: string[] = [];
  vi.spyOn(client, "request").mockImplementation((async (path: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${path}`);
    if (path.startsWith("/approvals/refused")) return refused;
    if (path === "/permissions/rules") return { rules: [{ id: 99 }] };
    if (path.startsWith("/proactive/items?")) return { items: typeof jobs === "function" ? jobs() : jobs };
    if (/^\/proactive\/items\/\d+\/accept$/.test(path)) return accept();
    return { ok: true };
  }) as never);
  return calls;
}
const doIt = () => screen.getByText("proactive.item.doIt");

describe("a stopped job's card waits out a scroll, as the away entries do", () => {
  it("holds its 「接着做」 while a scroll moves it under a still pointer, and looks held", async () => {
    const calls = serve({ jobs: [job(5)] });
    render(<AnswerGuardScope value={makeAnswerGuard()}>
      <div data-testid="conversation"><StoppedJobCards conversationId="c" onOpenConversation={vi.fn()} /></div></AnswerGuardScope>);
    await settle(600);                                               // the card has been there for a while
    expect(doIt()).not.toHaveAttribute("aria-disabled");
    fireEvent.scroll(screen.getByTestId("conversation"));            // a reply streams in; the conversation, stuck to the bottom, scrolls
    expect(doIt()).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(doIt());
    await settle();
    expect(calls).not.toContain("POST /proactive/items/5/accept");
    await settle(500);
    expect(doIt()).not.toHaveAttribute("aria-disabled");
    fireEvent.click(doIt());
    await settle();
    expect(calls).toContain("POST /proactive/items/5/accept");
  });

  it("a scroll there does not hold the slot's card, which floats", async () => {
    serve({ jobs: [job(5)] });
    const send = vi.fn();
    render(<AnswerGuardScope value={makeAnswerGuard()}><AskSlot send={send} />
      <div data-testid="conversation"><StoppedJobCards conversationId="c" onOpenConversation={vi.fn()} /></div></AnswerGuardScope>);
    frame(cmd("a"));
    await settle(600);
    fireEvent.scroll(screen.getByTestId("conversation"));
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).toHaveBeenCalledWith({ type: "confirm_run_command", call_id: "a", scope: "once" });
  });
});

describe("what moves in the conversation holds the slot's card (N5, N6, and the away entries)", () => {
  it("the away entries appearing above the messages", async () => {
    serve({ refused: [row(7)] });
    const send = vi.fn();
    const guard = makeAnswerGuard();
    const { rerender } = render(<AnswerGuardScope value={guard}><AskSlot send={send} /></AnswerGuardScope>);
    frame(cmd("a"));
    await settle(600);
    rerender(<AnswerGuardScope value={guard}><AskSlot send={send} /><NotDoneList conversationId="c" /></AnswerGuardScope>);
    await settle();                                                  // the list arrives on top and moves what was under the pointer
    expect(screen.getByTestId("inbox-refused")).toBeTruthy();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).not.toHaveBeenCalled();
    await settle(500);
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("a notice appearing above them", async () => {
    serve({ jobs: [job(5)], accept: async () => { throw new client.ApiError("no_model", 422); } });
    const send = vi.fn();
    render(<AnswerGuardScope value={makeAnswerGuard()}><AskSlot send={send} />
      <StoppedJobCards conversationId="c" onOpenConversation={vi.fn()} /></AnswerGuardScope>);
    frame(cmd("a"));
    await settle(600);
    fireEvent.click(doIt());                                         // no model: a notice comes up above the card
    await settle();
    expect(screen.getByRole("alert")).toBeTruthy();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).not.toHaveBeenCalled();
    await settle(500);
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("a card changing state", async () => {
    let status = "new";
    serve({ jobs: () => [job(5, status)], accept: async () => { status = "accepted"; return { job_id: "j2", conversation_id: "c" }; } });
    const send = vi.fn();
    render(<AnswerGuardScope value={makeAnswerGuard()}><AskSlot send={send} />
      <StoppedJobCards conversationId="c" onOpenConversation={vi.fn()} /></AnswerGuardScope>);
    frame(cmd("a"));
    await settle(600);
    fireEvent.click(doIt());                                         // started: the card turns into "Started as a background job"
    await settle();
    expect(screen.getByText("proactive.item.started")).toBeTruthy();
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).not.toHaveBeenCalled();
    await settle(500);
    fireEvent.click(screen.getByTestId("runcmd-run"));
    expect(send).toHaveBeenCalledTimes(1);
  });
});

describe("the away entries' buttons wait out a scroll, and look held (N10)", () => {
  it("「Always allow」 and its Undo", async () => {
    const calls = serve({ refused: [row(7)] });
    render(<AnswerGuardScope value={makeAnswerGuard()}><div data-testid="conversation"><NotDoneList conversationId="c" /></div></AnswerGuardScope>);
    await settle(600);
    fireEvent.scroll(screen.getByTestId("conversation"));
    expect(screen.getByTestId("inbox-refused-allow")).toHaveAttribute("aria-disabled", "true");
    await settle(500);
    expect(screen.getByTestId("inbox-refused-allow")).not.toHaveAttribute("aria-disabled");
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await settle(500);                                               // Undo has come up where "Always allow" was, and waited its hold out
    fireEvent.scroll(screen.getByTestId("conversation"));
    expect(screen.getByTestId("inbox-refused-undo")).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(screen.getByTestId("inbox-refused-undo"));
    await settle();
    expect(calls.filter((c) => c.startsWith("DELETE"))).toEqual([]);
    await settle(500);
    fireEvent.click(screen.getByTestId("inbox-refused-undo"));
    await settle();
    expect(calls).toContain("DELETE /permissions/rules/99");
  });
});
