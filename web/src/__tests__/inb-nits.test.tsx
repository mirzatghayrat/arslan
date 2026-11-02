/**
 * The small follow-ups left by the reviews of PR 611 and PR 605, in real English.
 * - #611 (1): a stopped job's card is held when the conversation's content moves it with no scroll at all (a short conversation, or
 *   one scrolled up while a reply grows above the card), not only when it scrolls.
 * - #611 (2): the reminder's menu choices (Snooze, Not useful) look held while a hold lasts, and a held pick keeps the menu open.
 * - #611 (3): the away list's own scrolling list holds its rows (G7); "Got it" looks held (R2); the held look is the visible one (R3).
 * - #605 (N3): the not-done list rendered through real English.
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import * as client from "../api/client";
import { StoppedJobCards } from "../components/conversation/WhileAway";
import { AnswerGuardScope, makeAnswerGuard } from "../components/kit/guard";
import NotDoneList from "../components/proactive/NotDoneList";

/** A ResizeObserver jsdom lacks: each one is kept, so a test can say the observed content changed size. */
const observers: { callback: ResizeObserverCallback; targets: Element[] }[] = [];
class FakeResizeObserver {
  private readonly entry: { callback: ResizeObserverCallback; targets: Element[] };
  constructor(callback: ResizeObserverCallback) { this.entry = { callback, targets: [] }; observers.push(this.entry); }
  observe(target: Element) { this.entry.targets.push(target); }
  unobserve() {}
  disconnect() { this.entry.targets = []; }
}
const resized = () => act(() => { for (const o of observers) if (o.targets.length) o.callback([], o as unknown as ResizeObserver); });

beforeEach(async () => {
  await i18n.changeLanguage("en");
  observers.length = 0;
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-01T10:00:00Z"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
const settle = async (ms = 0) => { for (let t = 0; t < ms; t += 50) await act(async () => { await vi.advanceTimersByTimeAsync(Math.min(50, ms - t)); });
  await act(async () => { await vi.advanceTimersByTimeAsync(0); }); };
const item = (id: number, kind = "job_followup") => ({ id, kind, title_key: `title.${kind}`, params: { goal: "x" }, evidence: [],
  goal: "Finish the report.", priority: "normal", status: "new", diagnosis: null, conversation_id: "c", job_id: "j1",
  created_at: "2026-11-01T09:00:00", snooze_until: null });
const row = (id: number) => ({ id, created_at: "2026-11-01T09:00:00Z", first_at: "2026-11-01T09:00:00Z", count: 1, conversation_id: "c",
  kind: "command", target: `rules:${id}`, detail: "mail -s hi me@x.com", always_ok: true,
  always: [{ kind: "legacy_rule", target: "send-mail", label: "sends email" }], unattended: false });

function serve({ items = [] as unknown[], refused = [] as unknown[] } = {}) {
  const calls: string[] = [];
  vi.spyOn(client, "request").mockImplementation((async (path: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${path}`);
    if (path.startsWith("/approvals/refused")) return refused;
    if (path === "/permissions/rules") return { rules: [{ id: 99 }] };
    if (path.startsWith("/proactive/items?")) return { items };
    return { ok: true };
  }) as never);
  return calls;
}
const cards = (items: unknown[]) => {
  const calls = serve({ items });
  render(<AnswerGuardScope value={makeAnswerGuard()}>
    <div data-testid="conversation"><div data-testid="reply">A reply</div><StoppedJobCards conversationId="c" onOpenConversation={vi.fn()} /></div>
  </AnswerGuardScope>);
  return calls;
};
const doIt = () => screen.getByRole("button", { name: "Do it" });

describe("a stopped job's card is held when the content around it moves, with no scroll (#611 review, 1)", () => {
  it("holds 「接着做」 while a reply growing above it moves it, in a conversation that never scrolls", async () => {
    const calls = cards([item(5)]);
    await settle(600);
    resized();                                                       // the first report is the observer's own, on observe
    expect(doIt()).not.toHaveAttribute("aria-disabled");
    resized();                                                       // a streamed chunk makes the content taller
    expect(doIt()).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(doIt());
    await settle();
    expect(calls).not.toContain("POST /proactive/items/5/accept");
    await settle(500);
    expect(doIt()).not.toHaveAttribute("aria-disabled");
  });

  it("watches the content the card sits in, not just the card", async () => {
    cards([item(5)]);
    await settle(600);
    const watched = observers.flatMap((o) => o.targets);
    expect(watched).toContain(screen.getByTestId("conversation"));
  });
});

describe("the reminder's menu choices show a hold, and keep a held pick (#611 review, 2)", () => {
  it("Snooze's choices look held and a held pick leaves the menu open; after the hold they work", async () => {
    const calls = cards([item(5)]);
    await settle(600);
    resized();
    fireEvent.click(screen.getByRole("button", { name: /Snooze/ }));
    resized();                                                       // a hold starts while the menu is open
    const tomorrow = screen.getByRole("menuitem", { name: "Until tomorrow" });
    expect(tomorrow).toHaveAttribute("aria-disabled", "true");
    expect(tomorrow.className).toContain("aria-disabled:opacity-50");
    fireEvent.click(tomorrow);
    await settle();
    expect(screen.getByRole("menuitem", { name: "Until tomorrow" })).toBeTruthy();   // still open: the pick was not dropped silently
    expect(calls.some((c) => c.includes("/snooze"))).toBe(false);
    await settle(500);
    fireEvent.click(screen.getByRole("menuitem", { name: "Until tomorrow" }));
    await settle();
    expect(calls.some((c) => c.includes("/proactive/items/5/snooze"))).toBe(true);
  });

  it("Not useful's choices look held too", async () => {
    cards([item(5)]);
    await settle(600);
    resized();
    fireEvent.click(screen.getByRole("button", { name: /Not useful/ }));
    resized();
    expect(screen.getByRole("menuitem", { name: "Dismiss this one" })).toHaveAttribute("aria-disabled", "true");
  });
});

describe("the gaps the #611 review found in the tests (3)", () => {
  it("the away list's own scrolling list holds its rows (G7)", async () => {
    serve({ refused: [row(7)] });
    render(<AnswerGuardScope value={makeAnswerGuard()}><NotDoneList conversationId="c" /></AnswerGuardScope>);
    await settle(600);
    const allow = within(screen.getByTestId("inbox-refused")).getAllByRole("button")[0];
    expect(allow).not.toHaveAttribute("aria-disabled");
    fireEvent.scroll(screen.getByTestId("inbox-refused").querySelector("ul")!);
    expect(allow).toHaveAttribute("aria-disabled", "true");
  });

  it("「知道了」 looks held, with the visible held style (R2, R3)", async () => {
    cards([item(6, "brief")]);
    await settle(600);
    resized();
    resized();
    const gotIt = screen.getByRole("button", { name: "Got it" });
    expect(gotIt).toHaveAttribute("aria-disabled", "true");
    expect(gotIt.className).toContain("aria-disabled:opacity-50");
    expect(gotIt.className).toContain("aria-disabled:cursor-not-allowed");
  });
});

describe("the not-done list in real English (#605 re-check, N3)", () => {
  it("renders its title and rows through the real translations, with no raw key showing", async () => {
    serve({ refused: [row(7)] });
    render(<AnswerGuardScope value={makeAnswerGuard()}><NotDoneList conversationId="c" /></AnswerGuardScope>);
    await settle();
    const list = screen.getByTestId("inbox-refused");
    expect(list).toHaveTextContent("Not done while you were away");
    expect(list).toHaveTextContent("mail -s hi me@x.com");
    expect(list.textContent).not.toMatch(/\b(inbox|proactive|whileAway)\.[a-zA-Z_]+/);
  });
});
