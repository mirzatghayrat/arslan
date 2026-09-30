/**
 * The Inbox: what it shows, and that each button does exactly one thing through the API.
 * Real i18n (English), so a raw key on screen is a failure rather than a pass.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { ApiError } from "../api/client";
import type { ProactiveItem } from "../api/proactive";
import ProactiveInbox from "../components/proactive/ProactiveInbox";

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
const props = () => ({ onOpenSettings: vi.fn(), onOpenConversation: vi.fn() });
const show = async (items: ProactiveItem[], p = props()) => {
  api.items.mockResolvedValue({ items });
  render(<ProactiveInbox {...p} />);
  await waitFor(() => expect(api.items).toHaveBeenCalled());
  return p;
};

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.seen.mockResolvedValue({ ok: true });
  void i18n.changeLanguage("en");
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("what is shown", () => {
  it("shows the title, the sentence and the outside text in quotation marks", async () => {
    await show([item()]);
    const card = await screen.findByTestId("proactive-item-1");
    expect(within(card).getByRole("heading", { name: "“Pricing” changed" })).toBeTruthy();
    expect(within(card).getByText("“Pricing” changed: 1 added, 1 removed.")).toBeTruthy();
    const quote = within(card).getByText("“Pro plan: $12”");
    expect(quote.tagName).toBe("BLOCKQUOTE");
    expect(quote.getAttribute("title")).toBe("Quoted text. Arslan does not follow instructions inside it.");
  });

  it("never prints a raw key or placeholder", async () => {
    await show([item(), item({ id: 2, kind: "brief", title_key: "title.brief", params: { day: "2026-09-30" }, goal: "",
      evidence: [{ key: "brief.open", params: { count: 2, kinds: {} } }] })]);
    await screen.findByTestId("proactive-item-2");
    expect(document.body.textContent).not.toMatch(/proactive\.|web\.changed|brief\.open|\{\{/);
  });

  it("renders page text as text, not as markup", async () => {
    await show([item({ evidence: [{ key: "web.added", params: {}, quote: "<img src=x onerror=alert(1)>" }] })]);
    await screen.findByText("“<img src=x onerror=alert(1)>”");
    expect(document.querySelector("img")).toBeNull();
  });

  it("flags what needs a look and shows a guess as a guess", async () => {
    await show([item({ priority: "high", diagnosis: { cause: "The vendor redesigned the page.", next_step: "Open it and compare.", model: "m", usd: 0.0002 } })]);
    expect(await screen.findByText("Needs a look")).toBeTruthy();
    const guess = screen.getByTestId("proactive-diagnosis");
    expect(within(guess).getByText("Arslan's guess")).toBeTruthy();
    expect(within(guess).getByText("Next: Open it and compare.")).toBeTruthy();
    expect(within(guess).getByText("Written by a model from the evidence above. It may be wrong.")).toBeTruthy();
  });

  it("offers Got it, not Do it, for a brief", async () => {
    await show([item({ kind: "brief", title_key: "title.brief", goal: "", evidence: [{ key: "brief.open", params: { count: 1, kinds: {} } }] })]);
    await screen.findByRole("button", { name: "Got it" });
    expect(screen.queryByRole("button", { name: "Do it" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Not useful" })).toBeNull();
  });

  it("explains the empty inbox and points at what to watch", async () => {
    const p = await show([]);
    expect(await screen.findByText("Nothing needs your attention")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Choose what to watch" }));
    expect(p.onOpenSettings).toHaveBeenCalledOnce();
  });

  it("says when the list could not be loaded, and retries", async () => {
    api.items.mockRejectedValueOnce(new Error("down")).mockResolvedValue({ items: [item()] });
    render(<ProactiveInbox {...props()} />);
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("Couldn't load the inbox."));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("proactive-item-1")).toBeTruthy();
  });
});

describe("doing things", () => {
  it("Do it on an item with its own conversation starts the job there", async () => {
    api.accept.mockResolvedValue({ job_id: "j1", conversation_id: "thread-origin" });
    const p = await show([item({ kind: "job_followup", title_key: "title.job_followup", params: { goal: "x" }, conversation_id: "thread-origin",
      evidence: [{ key: "job.reason.other", params: {} }] })]);
    fireEvent.click(await screen.findByRole("button", { name: "Do it" }));
    await waitFor(() => expect(p.onOpenConversation).toHaveBeenCalledWith("thread-origin", false));
    expect(api.accept).toHaveBeenCalledWith(1, undefined);
  });

  it("Do it on an item with no conversation makes a new one and says it is new", async () => {
    api.accept.mockImplementation(async (_id: number, conversation: string) => ({ job_id: "j2", conversation_id: conversation }));
    const p = await show([item()]);
    fireEvent.click(await screen.findByRole("button", { name: "Do it" }));
    await waitFor(() => expect(p.onOpenConversation).toHaveBeenCalled());
    const [, made] = api.accept.mock.calls[0];
    expect(made).toMatch(/^thread-[0-9a-f-]{36}$/);
    expect(p.onOpenConversation).toHaveBeenCalledWith(made, true);
  });

  it("shows Starting… and blocks a second press while the job starts", async () => {
    let release: (v: unknown) => void = () => {};
    api.accept.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    await show([item()]);
    fireEvent.click(await screen.findByRole("button", { name: "Do it" }));
    const starting = await screen.findByRole("button", { name: "Starting…" });
    expect((starting as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { release({ job_id: "j", conversation_id: "thread-x" }); });
  });

  it("tells the truth when someone else already handled it, and refreshes", async () => {
    api.accept.mockRejectedValue(new ApiError("already_handled", 409));
    await show([item()]);
    fireEvent.click(await screen.findByRole("button", { name: "Do it" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Already handled. The list was refreshed.");
    await waitFor(() => expect(api.items.mock.calls.length).toBeGreaterThanOrEqual(2));
  });

  it("snoozes for the chosen number of days", async () => {
    api.snooze.mockResolvedValue({ ok: true });
    await show([item()]);
    await screen.findByTestId("proactive-item-1");
    fireEvent.click(screen.getByRole("button", { name: "3 days" }));
    await waitFor(() => expect(api.snooze).toHaveBeenCalledWith(1, 3));
  });

  it.each([["Dismiss this one", undefined], ["Stop watching this", "source"], ["Stop this kind of notice", "kind"]])(
    "Not useful → %s", async (label, mute) => {
      api.dismiss.mockResolvedValue({ ok: true });
      await show([item()]);
      await screen.findByTestId("proactive-item-1");
      fireEvent.click(screen.getByRole("button", { name: label as string }));
      await waitFor(() => expect(api.dismiss).toHaveBeenCalledWith(1, mute));
    });

  it("a one-off job has nothing to stop watching", async () => {
    await show([item({ kind: "job_followup", title_key: "title.job_followup", params: { goal: "x" }, conversation_id: "c",
      evidence: [{ key: "job.reason.other", params: {} }] })]);
    await screen.findByTestId("proactive-item-1");
    expect(screen.queryByRole("button", { name: "Stop watching this" })).toBeNull();
    expect(screen.getByRole("button", { name: "Stop this kind of notice" })).toBeTruthy();
  });

  it("Check now reports what it found", async () => {
    api.scan.mockResolvedValueOnce({ created: 0, rejected: {} }).mockResolvedValueOnce({ created: 2, rejected: {} });
    await show([item()]);
    fireEvent.click(await screen.findByRole("button", { name: "Check now" }));
    expect((await screen.findByRole("status")).textContent).toBe("Nothing new.");
    fireEvent.click(screen.getByRole("button", { name: "Check now" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("2 new items."));
  });
});

describe("the other tabs", () => {
  it("shows what became of a handled item and a way back to the conversation", async () => {
    const p = props();
    api.items.mockImplementation(async (scope: string) => ({ items: scope === "done"
      ? [item({ status: "accepted", conversation_id: "thread-7", job_id: "j" }), item({ id: 2, status: "dismissed" })] : [] }));
    render(<ProactiveInbox {...p} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Done" }));
    expect(await screen.findByText("Started as a background job")).toBeTruthy();
    expect(screen.getByText("Dismissed")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Do it" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open the conversation" }));
    expect(p.onOpenConversation).toHaveBeenCalledWith("thread-7", false);
  });

  it("a snoozed item can still be acted on and says until when", async () => {
    api.items.mockResolvedValue({ items: [item({ status: "snoozed", snooze_until: "2026-10-03T09:00:00" })] });
    render(<ProactiveInbox {...props()} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Snoozed" }));
    expect(await screen.findByRole("button", { name: "Do it" })).toBeTruthy();
    expect(screen.getByText(/^Snoozed until /)).toBeTruthy();
  });
});

describe("unread", () => {
  it("marks only what is still new, and only after it has been in front of the user", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.items.mockResolvedValue({ items: [item({ id: 1, status: "new" }), item({ id: 2, status: "seen" }), item({ id: 3, status: "new" })] });
    render(<ProactiveInbox {...props()} />);
    await screen.findByTestId("proactive-item-3");
    expect(api.seen).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    expect(api.seen).toHaveBeenCalledWith([1, 3]);
  });

  it("does not mark anything read when the user leaves straight away", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.items.mockResolvedValue({ items: [item()] });
    const view = render(<ProactiveInbox {...props()} />);
    await screen.findByTestId("proactive-item-1");
    view.unmount();
    await vi.advanceTimersByTimeAsync(5000);
    expect(api.seen).not.toHaveBeenCalled();
  });

  it("does not mark the Done or Snoozed lists as read", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.items.mockImplementation(async (scope: string) => ({ items: scope === "open" ? [] : [item({ status: "new" })] }));
    render(<ProactiveInbox {...props()} />);
    fireEvent.click(await screen.findByRole("tab", { name: "Snoozed" }));
    await screen.findByTestId("proactive-item-1");
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(api.seen).not.toHaveBeenCalled();
  });
});
