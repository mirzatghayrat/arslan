/** 0.1.61 §A4 (PR 2b Task 4, fix round 1: M1, M4), moved from inbox-hardening.test.tsx when the Inbox went (INB5b-2). What "Always allow"
 *  will store is shown in full, one rule to a line, wrapping instead of being clipped; a durable one-click is not taken by a row that shifted
 *  under the pointer, and can be undone for ten seconds. The list (NotDoneList) now sits in a conversation and on the Scheduled page. The
 *  file's card half (M3, a card closing at its own expiry) is covered by the ask slot's tests: card-expiry-kinds, card-lists, card-hardening
 *  and card-v2. */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, act, within } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import * as client from "../api/client";
import NotDoneList from "../components/proactive/NotDoneList";
import { isolate } from "../lib/outsideText";
import { ANSWER_GUARD_MS, CARD_MS } from "../components/kit";

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-13T10:00:00Z")); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

describe("what Always allow will store is shown in full (M1)", () => {
  const LONG = "https://example.com/" + "a".repeat(180);
  const base = { id: 40, created_at: "2026-10-12T09:00:00Z", first_at: "2026-10-12T09:00:00Z", count: 1, conversation_id: "c", always_ok: true };
  function serve(rows: unknown[]) {
    return vi.spyOn(client, "request").mockImplementation((async (path: string, init?: RequestInit) => {
      if (path === "/approvals/refused?hours=24") return rows;
      if (path === "/permissions/rules" && init?.method === "POST") return { id: 9, rules: [{ id: 9 }] };
      return [];
    }) as never);
  }
  const shown = async () => { render(<NotDoneList />); await advance(0); };

  it("a long unbroken label wraps, whole, and is the line's title; it is not one clipped line", async () => {
    serve([{ ...base, kind: "site", target: "x.com", detail: "", always: [{ kind: "site", target: "x.com", label: LONG }] }]);
    await shown();
    const rule = screen.getByTestId("inbox-refused-rule");
    expect(rule.textContent).toBe(`inbox.alwaysStores:${JSON.stringify({ what: isolate(LONG) })}`);     // isolated in the sentence (#602 review)
    expect(rule.className).toContain("[overflow-wrap:anywhere]");
    expect(rule.className).not.toMatch(/\btruncate\b|\bwhitespace-nowrap\b|\bline-clamp/);
    expect(rule).toHaveAttribute("title", isolate(LONG));
  });

  it("every rule is a line of its own, each in the words its card used, in order", async () => {
    serve([{ ...base, kind: "app", target: "a\u001eb\u001ec", detail: "Notes\nMail\nBear",
      always: [{ kind: "app", target: "com.apple.Notes", label: "Notes" }, { kind: "app", target: "com.apple.mail", label: "Mail" },
               { kind: "app", target: "com.bear", label: "" }] }]);
    await shown();
    const rules = within(screen.getByTestId("inbox-refused-stores")).getAllByTestId("inbox-refused-rule");
    expect(rules.map((r) => r.textContent)).toEqual(["Notes", "Mail", "com.bear"]
      .map((name) => `inbox.alwaysStores:${JSON.stringify({ what: isolate(name) })}`));
  });

  it("a many-app entry names each app on a line of its own, never merged into one string", async () => {
    serve([{ ...base, kind: "app", target: "a\u001eb\u001ec", detail: "Notes\nMail\nBear",
      always: [{ kind: "app", target: "a", label: "Notes" }] }]);
    await shown();
    expect(screen.getAllByTestId("inbox-refused-what").map((w) => w.textContent)).toEqual(["Notes", "Mail", "Bear"]);
  });

  it("a target with the app separator reads one app to a line too, and a one-line command stays one", async () => {
    serve([{ ...base, id: 41, kind: "app", target: "Notes\u001eMail", detail: "", always: [] }, { ...base, id: 42, kind: "command", target: "rules:x", detail: "mail  -s hi", always: [] }]);
    await shown();
    expect(within(screen.getAllByTestId("inbox-refused-row")[0]).getAllByTestId("inbox-refused-what").map((w) => w.textContent)).toEqual(["Notes", "Mail"]);
    expect(within(screen.getAllByTestId("inbox-refused-row")[1]).getAllByTestId("inbox-refused-what").map((w) => w.textContent)).toEqual(["mail -s hi"]);
  });
});

describe("Always allow is guarded, and can be undone for ten seconds (M4)", () => {
  const entry = (id: number, target: string) => ({ id, created_at: "2026-10-12T09:00:00Z", first_at: "2026-10-12T09:00:00Z", count: 1, conversation_id: "c",
    kind: "site", target, detail: target, always_ok: true, always: [{ kind: "site", target, label: target }] });
  let list: unknown[];
  let posts: string[];
  let deletes: string[];
  let post: (body: string) => unknown;
  let del: (path: string) => unknown;
  function serve() {
    posts = []; deletes = [];
    post = () => ({ id: 100, rules: [{ id: 100 }, { id: 101 }] });
    del = () => ({ ok: true });
    return vi.spyOn(client, "request").mockImplementation((async (path: string, init?: RequestInit) => {
      if (path === "/approvals/refused?hours=24") return list;
      if (path === "/permissions/rules" && init?.method === "POST") { posts.push(String(init.body)); return post(String(init.body)); }
      if (path.startsWith("/permissions/rules/") && init?.method === "DELETE") { deletes.push(path); return del(path); }
      return [];
    }) as never);
  }
  const rows = () => screen.getAllByTestId("inbox-refused-row");

  it("a row that shifts under the pointer is not clicked: a click within 500 ms of the list changing answers nothing, and both show it", async () => {
    list = [entry(1, "a.com")];
    serve();
    render(<NotDoneList />);
    await advance(0);
    expect(screen.getByTestId("inbox-refused-allow")).toHaveAttribute("aria-disabled", "true");     // the first list moved what was under it
    await advance(ANSWER_GUARD_MS);
    expect(screen.getByTestId("inbox-refused-allow")).not.toHaveAttribute("aria-disabled");
    list = [entry(2, "b.com"), entry(1, "a.com")];                                                // a new entry comes in on top
    await advance(30_000);                                                                         // the next poll
    expect(rows()[0]).toHaveTextContent("b.com");
    const first = within(rows()[0]).getByTestId("inbox-refused-allow");
    expect(first).toHaveAttribute("aria-disabled", "true");
    expect(first).not.toBeDisabled();
    fireEvent.click(first);
    await advance(0);
    expect(posts).toEqual([]);
    await advance(ANSWER_GUARD_MS);
    expect(first).not.toHaveAttribute("aria-disabled");
    fireEvent.click(first);
    await advance(0);
    expect(posts).toEqual([JSON.stringify({ refused_id: 2 })]);
  });

  it("a poll that finds the same list changes nothing and holds nothing", async () => {
    list = [entry(1, "a.com")];
    serve();
    render(<NotDoneList />);
    await advance(0);
    await advance(ANSWER_GUARD_MS);                                // the list has just appeared: held for 500 ms
    await advance(30_000);
    expect(screen.getByTestId("inbox-refused-allow")).not.toHaveAttribute("aria-disabled");
  });

  it("the button is off while its own request is in flight: a second click sends nothing", async () => {
    list = [entry(1, "a.com")];
    serve();
    let release: (v: unknown) => void = () => {};
    post = () => new Promise((ok) => { release = ok; });
    render(<NotDoneList />);
    await advance(0);
    await advance(ANSWER_GUARD_MS);                                // the list has just appeared: held for 500 ms
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await advance(0);
    expect(screen.getByTestId("inbox-refused-allow")).toBeDisabled();
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await advance(0);
    expect(posts).toHaveLength(1);
    release({ id: 100, rules: [{ id: 100 }] });
    await advance(0);
    expect(screen.getByTestId("inbox-refused-allowed")).toBeInTheDocument();
  });

  it("after Always allow, Undo is offered for 10 s and then goes; the allowance stands", async () => {
    list = [entry(1, "a.com")];
    serve();
    render(<NotDoneList />);
    await advance(0);
    await advance(ANSWER_GUARD_MS);                                // the list has just appeared: held for 500 ms
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await advance(0);
    expect(screen.getByTestId("inbox-refused-allowed")).toHaveTextContent("inbox.allowedNow");
    expect(screen.getByTestId("inbox-refused-undo")).toHaveTextContent("inbox.undo");
    await advance(9_900);
    expect(screen.getByTestId("inbox-refused-undo")).toBeInTheDocument();
    await advance(200);
    expect(screen.queryByTestId("inbox-refused-undo")).toBeNull();
    expect(screen.getByTestId("inbox-refused-allowed")).toBeInTheDocument();
    expect(deletes).toEqual([]);
  });

  it("Undo deletes exactly the rules the click created, and the row asks again", async () => {
    list = [entry(1, "a.com")];
    serve();
    render(<NotDoneList />);
    await advance(0);
    await advance(ANSWER_GUARD_MS);                                // the list has just appeared: held for 500 ms
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await advance(0);
    await advance(ANSWER_GUARD_MS);                                // Undo came up where "Always allow" was: it answers 500 ms later
    fireEvent.click(screen.getByTestId("inbox-refused-undo"));
    await advance(0);
    expect(deletes.sort()).toEqual(["/permissions/rules/100", "/permissions/rules/101"]);
    expect(screen.queryByTestId("inbox-refused-allowed")).toBeNull();
    expect(screen.queryByTestId("inbox-refused-undo")).toBeNull();
    expect(screen.getByTestId("inbox-refused-stores")).toBeInTheDocument();                       // asked again, with what it would store
    expect(screen.getByTestId("inbox-refused-allow")).toBeInTheDocument();
  });

  it("an answer with no list of rules is one rule: its id", async () => {
    list = [entry(1, "a.com")];
    serve();
    post = () => ({ id: 77 });
    render(<NotDoneList />);
    await advance(0);
    await advance(ANSWER_GUARD_MS);                                // the list has just appeared: held for 500 ms
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await advance(0);
    await advance(ANSWER_GUARD_MS);                                // Undo came up where "Always allow" was: it answers 500 ms later
    fireEvent.click(screen.getByTestId("inbox-refused-undo"));
    await advance(0);
    expect(deletes).toEqual(["/permissions/rules/77"]);
  });

  it("a rule that is gone already (404) counts as undone; a delete that fails keeps Undo for a retry", async () => {
    list = [entry(1, "a.com")];
    serve();
    del = (path) => { throw new client.ApiError("no such rule", path.endsWith("100") ? 404 : 500); };
    render(<NotDoneList />);
    await advance(0);
    await advance(ANSWER_GUARD_MS);                                // the list has just appeared: held for 500 ms
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await advance(0);
    await advance(ANSWER_GUARD_MS);                                // Undo came up where "Always allow" was: it answers 500 ms later
    fireEvent.click(screen.getByTestId("inbox-refused-undo"));
    await advance(0);
    expect(screen.getByTestId("inbox-refused-undo")).toBeInTheDocument();                         // 101 failed: still allowed, still undoable
    expect(screen.getByTestId("inbox-refused-allowed")).toBeInTheDocument();
    del = () => { throw new client.ApiError("no such rule", 404); };
    fireEvent.click(screen.getByTestId("inbox-refused-undo"));
    await advance(0);
    expect(screen.queryByTestId("inbox-refused-undo")).toBeNull();
    expect(screen.queryByTestId("inbox-refused-allowed")).toBeNull();
  });

  it("a poll while Undo is open that no longer lists the row (the server leaves out what is allowed) does not take Undo away; when the ten seconds are over the row goes", async () => {
    list = [entry(1, "a.com"), entry(2, "b.com")];
    serve();
    render(<NotDoneList />);
    await advance(0);                                                                             // the first poll was at once; the next is at 30 s
    await advance(25_000);
    fireEvent.click(within(rows()[0]).getByTestId("inbox-refused-allow"));
    await advance(0);
    list = [entry(2, "b.com")];                                                                   // a.com is allowed now: the server omits it
    await advance(5_100);                                                                         // the poll lands 5 s into the ten
    expect(rows()).toHaveLength(2);
    expect(within(rows()[0]).getByTestId("inbox-refused-undo")).toBeInTheDocument();
    await advance(5_000);                                                                         // 10.1 s: Undo is over, and the row with it
    expect(rows()).toHaveLength(1);
    expect(rows()[0]).toHaveTextContent("b.com");
  });

  it("an undone row that is still listed is not shown twice", async () => {
    list = [entry(1, "a.com")];
    serve();
    render(<NotDoneList />);
    await advance(0);
    await advance(ANSWER_GUARD_MS);                                // the list has just appeared: held for 500 ms
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await advance(0);
    await advance(30_000);                                                                        // a poll that still lists it (the mock does)
    expect(rows()).toHaveLength(1);
  });
});
