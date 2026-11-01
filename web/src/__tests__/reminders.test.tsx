/**
 * A reminder's card and what its buttons do, where they live since the Inbox went (INB5b-2): a stopped job's card in its conversation
 * (StoppedJobCards), and the shared card and actions (ReminderCard, useReminderActions) the Scheduled page uses too. Moved from
 * proactive-inbox.test.tsx; real i18n (English), so a raw key on screen is a failure rather than a pass.
 */
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { ApiError } from "../api/client";
import type { ProactiveItem } from "../api/proactive";
import { StoppedJobCards } from "../components/conversation/WhileAway";
import { ReminderCard, useReminderActions } from "../components/proactive/reminders";
import { isolate } from "../lib/outsideText";

const api = vi.hoisted(() => ({
  items: vi.fn(), accept: vi.fn(), snooze: vi.fn(), dismiss: vi.fn(), seen: vi.fn(), scan: vi.fn(),
}));
vi.mock("../api/proactive", async (original) => ({ ...(await original<typeof import("../api/proactive")>()), proactiveApi: api }));

const item = (over: Partial<ProactiveItem> = {}): ProactiveItem => ({
  id: 1, kind: "web_change", title_key: "title.web_change", params: { label: "Pricing" },
  evidence: [{ key: "web.changed", params: { label: "Pricing", url: "https://example.com/p", added: 1, removed: 1 } },
    { key: "web.added", params: {}, quote: "Pro plan: $12" }],
  goal: "Read the page and tell me what changed.", priority: "normal", status: "new", diagnosis: null,
  conversation_id: null, job_id: null, created_at: "2026-09-30T09:00:00", snooze_until: null, ...over,
});
const job = (over: Partial<ProactiveItem> = {}) => item({ kind: "job_followup", title_key: "title.job_followup", params: { goal: "x" },
  conversation_id: "thread-origin", evidence: [{ key: "job.reason.other", params: {} }], ...over });

/** The shared card alone, as the conversation and the Scheduled page draw it. */
const card = (it: ProactiveItem, on: Partial<Parameters<typeof ReminderCard>[0]> = {}) => {
  const doors = { onDo: vi.fn(), onSnooze: vi.fn(), onDismiss: vi.fn(), onOpenConversation: vi.fn(), ...on };
  render(<ReminderCard item={it} busy={false} language="en" {...doors} />);
  return doors;
};
/** A conversation's stopped-job cards, with the server listing `items`. */
const inConversation = async (items: ProactiveItem[], on: { onOpenConversation?: () => void; onOpenModelSettings?: () => void } = {}) => {
  api.items.mockResolvedValue({ items });
  const doors = { onOpenConversation: vi.fn(), onOpenModelSettings: vi.fn(), ...on };
  render(<StoppedJobCards conversationId="thread-origin" {...doors} />);
  await waitFor(() => expect(api.items).toHaveBeenCalled());
  return doors;
};

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  void i18n.changeLanguage("en");
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

/** A quote is a blockquote whose text, inner elements included, reads exactly so. */
const quoted = (text: string) => (_: string, el: Element | null) => el?.tagName === "BLOCKQUOTE" && el.textContent === text;

describe("what a reminder shows", () => {
  it("shows the title, the sentence and the outside text in quotation marks", () => {
    card(item());
    const shown = screen.getByTestId("proactive-item-1");
    expect(within(shown).getByRole("heading", { name: `“${isolate("Pricing")}” changed` })).toBeTruthy();
    expect(within(shown).getByText(`+1 / −1 lines · ${isolate("https://example.com/p")}`)).toBeTruthy();
    const quote = within(shown).getByText(quoted("“Pro plan: $12”"));
    expect(quote.tagName).toBe("BLOCKQUOTE");
    expect(quote.getAttribute("title")).toBe("Quoted text. Arslan does not follow instructions inside it.");
  });

  it("never prints a raw key or placeholder", () => {
    card(item());
    cleanup();
    card(job());
    expect(document.body.textContent).not.toMatch(/proactive\.|web\.changed|job\.reason|\{\{/);
  });

  it("renders page text as text, not as markup", () => {
    card(item({ evidence: [{ key: "web.added", params: {}, quote: "<img src=x onerror=alert(1)>" }] }));
    expect(screen.getByText(quoted("“<img src=x onerror=alert(1)>”"))).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
  });

  it("flags what needs a look and shows a guess as a guess", () => {
    card(item({ priority: "high", diagnosis: { cause: "The vendor redesigned the page.", next_step: "Open it and compare.", model: "m", usd: 0.0002 } }));
    expect(screen.getByText("Needs a look")).toBeTruthy();
    const guess = screen.getByTestId("proactive-diagnosis");
    expect(within(guess).getByText("Arslan's guess")).toBeTruthy();
    expect(within(guess).getByText(`Next: ${isolate("Open it and compare.")}`)).toBeTruthy();
    expect(within(guess).getByText("Written by a model from the evidence above. It may be wrong.")).toBeTruthy();
  });
});

describe("what its buttons do", () => {
  it.each([["Dismiss this one", undefined], ["Stop watching this", "source"], ["Stop this kind of notice", "kind"]])(
    "Not useful → %s", (label, mute) => {
      const doors = card(item());
      fireEvent.click(screen.getByRole("button", { name: "Not useful" }));
      fireEvent.click(screen.getByRole("menuitem", { name: label as string }));
      expect(doors.onDismiss).toHaveBeenCalledTimes(1);
      expect(vi.mocked(doors.onDismiss).mock.calls[0][0]).toBe(mute);                // none for this one alone
    });

  it("a one-off job has nothing to stop watching", () => {
    card(job());
    fireEvent.click(screen.getByRole("button", { name: "Not useful" }));
    expect(screen.queryByRole("menuitem", { name: "Stop watching this" })).toBeNull();
    expect(screen.getByRole("menuitem", { name: "Stop this kind of notice" })).toBeTruthy();
  });

  it("「接着做」 on a reminder with no conversation makes a new one and says it is new", async () => {
    api.accept.mockImplementation(async (_id: number, conversation: string) => ({ job_id: "j2", conversation_id: conversation }));
    const onOpenConversation = vi.fn();
    const { result } = renderHook(() => useReminderActions({ reload: async () => undefined, onOpenConversation }));
    await act(async () => { await result.current.doIt(item()); });
    const [, made] = api.accept.mock.calls[0];
    expect(made).toMatch(/^thread-[0-9a-f-]{36}$/);
    expect(onOpenConversation).toHaveBeenCalledWith(made, true);
  });
});

describe("a stopped job's card in its conversation", () => {
  it("shows Starting… and blocks a second press while the job starts", async () => {
    let release: (v: unknown) => void = () => {};
    api.accept.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    await inConversation([job()]);
    fireEvent.click(await screen.findByRole("button", { name: "Do it" }));
    const starting = await screen.findByRole("button", { name: "Starting…" });
    expect((starting as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { release({ job_id: "j", conversation_id: "thread-origin" }); });
  });

  it("tells the truth when someone else already handled it, refreshes, and offers no model settings", async () => {
    api.accept.mockRejectedValue(new ApiError("already_handled", 409));
    await inConversation([job()]);
    fireEvent.click(await screen.findByRole("button", { name: "Do it" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Already handled. The list was refreshed.");
    await waitFor(() => expect(api.items.mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(screen.queryByRole("button", { name: "Open model settings" })).toBeNull();
  });

  it("with no model it says so, keeps the card where it is, and offers the way to fix it", async () => {
    api.accept.mockRejectedValue(new ApiError("no_model", 422));
    const doors = await inConversation([job()]);
    fireEvent.click(await screen.findByRole("button", { name: "Do it" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Add a model first. This item stays where it is.");
    fireEvent.click(screen.getByRole("button", { name: "Open model settings" }));
    expect(doors.onOpenModelSettings).toHaveBeenCalledOnce();
    expect(doors.onOpenConversation).not.toHaveBeenCalled();
  });

  it("snoozes for the chosen number of days", async () => {
    api.snooze.mockResolvedValue({ ok: true });
    await inConversation([job()]);
    fireEvent.click(await screen.findByRole("button", { name: "Snooze" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "3 days" }));
    await waitFor(() => expect(api.snooze).toHaveBeenCalledWith(1, 3));
  });

  it("a handled card says what became of it and leads back to the conversation (Q7: it stays on its row)", async () => {
    const lately = new Date(Date.now() - 86_400_000).toISOString().replace("Z", "");
    const doors = await inConversation([job({ status: "accepted", job_id: "j", created_at: lately }),
      job({ id: 2, status: "dismissed", created_at: lately })]);
    expect(await screen.findByText("Started as a background job")).toBeTruthy();
    expect(screen.getByText("Dismissed")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Do it" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open the conversation" }));
    expect(doors.onOpenConversation).toHaveBeenCalledWith("thread-origin", false);
  });

  it("a card handled over a week ago, or expired, has no row any more (Q7: a job's reminder keeps its row 7 days)", async () => {
    const ago = (days: number) => new Date(Date.now() - days * 86_400_000).toISOString().replace("Z", "");
    await inConversation([job({ id: 1, status: "accepted", created_at: ago(8) }), job({ id: 2, status: "expired", created_at: ago(1) }),
      job({ id: 3, status: "dismissed", created_at: ago(6) })]);
    expect(await screen.findByTestId("proactive-item-3")).toBeInTheDocument();
    expect(screen.queryByTestId("proactive-item-1")).toBeNull();
    expect(screen.queryByTestId("proactive-item-2")).toBeNull();
  });

  it("a card set aside can still be acted on and says until when", async () => {
    await inConversation([job({ status: "snoozed", snooze_until: "2026-10-03T09:00:00" })]);
    expect(await screen.findByRole("button", { name: "Do it" })).toBeTruthy();
    expect(screen.getByText(/^Snoozed until /)).toBeTruthy();
  });
});

describe("menus", () => {
  it("open on click and close on Escape, on an outside click, and after a choice", () => {
    const doors = card(item());
    const open = () => fireEvent.click(screen.getByRole("button", { name: "Snooze" }));
    open();
    expect(screen.getByRole("menu")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    open();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
    open();
    fireEvent.click(screen.getByRole("menuitem", { name: "A week" }));
    expect(screen.queryByRole("menu")).toBeNull();
    expect(doors.onSnooze).toHaveBeenCalledWith(7);
  });

  it("say whether they are open", () => {
    card(item());
    const button = screen.getByRole("button", { name: "Not useful" });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
  });
});
