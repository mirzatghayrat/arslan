/** 0.1.61 §A4 (PR 2b final re-review): one gesture answers one thing in the Inbox, also when a section moves for a reason that is not a new
 *  list from the server.
 *  (d) The waiting cards' section can come back as its error notice alone (an answer refused after the last card left): it pushes the rows of
 *      "Not done while you were away" down, and a click aimed at one of them must not be taken for the row that moved under the pointer.
 *  (u) A row allowed a moment ago stays in its place while its ten-second Undo is open, even when the server no longer lists it. When the Undo
 *      ends — or is pressed — that row leaves and the rows below move up: the second click of a double-click on Undo must not become an
 *      "Always allow" on the row that moved into its place. */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import * as client from "../api/client";
import { ApiError } from "../api/client";
import ProactiveInbox from "../components/proactive/ProactiveInbox";

const api = vi.hoisted(() => ({
  items: vi.fn(), accept: vi.fn(), snooze: vi.fn(), dismiss: vi.fn(), seen: vi.fn(), scan: vi.fn(),
}));
vi.mock("../api/proactive", async (original) => ({ ...(await original<typeof import("../api/proactive")>()), proactiveApi: api }));

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.items.mockResolvedValue({ items: [] });
  api.seen.mockResolvedValue({ ok: true });
  void i18n.changeLanguage("en");
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
// React draws what one act schedules only when the act ends: a step at a time, so each change is drawn when it comes.
const settle = async (ms = 0) => { for (let t = 0; t < ms; t += 50) await act(async () => { await vi.advanceTimersByTimeAsync(Math.min(50, ms - t)); });
  await act(async () => { await vi.advanceTimersByTimeAsync(0); }); };

const ask = (id: string) => ({ call_id: id, conversation_id: "conv-1", opened_at: Date.now() / 1000, expires_at: Date.now() / 1000 + 1700,
  frame: { type: "propose_run_command", call_id: id, pretty: "echo hi", reason: "", options: ["once", "conversation"], perm_kind: "command" } });
const row = (id: number, detail: string) => ({ id, created_at: "2026-10-13T09:00:00Z", first_at: "2026-10-13T09:00:00Z", count: 1, conversation_id: "c",
  kind: "command", target: `rules:${id}`, detail, always_ok: true, always: [{ kind: "legacy_rule", target: `r${id}`, label: `rule ${id}` }] });
const show = () => render(<ProactiveInbox onOpenSettings={vi.fn()} onOpenConversation={vi.fn()} onOpenModelSettings={vi.fn()} />);
const rowAt = (i: number) => screen.getAllByTestId("inbox-refused-row")[i];

/** The server: what waits, what was not done, and every rule made (POST) or unmade (DELETE). An "Always allow" makes the entry leave the list;
 *  its Undo brings it back. */
function serve(pending: () => unknown[], answer?: () => Promise<unknown>) {
  const made: string[] = [];
  let listed = [row(7, "mail -s hi me@x.com"), row(8, "mail -s again me@x.com")];
  vi.spyOn(client, "request").mockImplementation((async (path: string, init?: RequestInit) => {
    if (path === "/approvals/pending") return pending();
    if (path.startsWith("/approvals/refused")) return listed;
    if (path.endsWith("/answer") && answer) return answer();
    if (path === "/permissions/rules" && init?.method === "POST") {
      const id = JSON.parse(String(init.body)).refused_id as number;
      made.push(`allow ${id}`);
      listed = listed.filter((r) => r.id !== id);
      return { rules: [{ id: 900 + id }] };
    }
    if (path.startsWith("/permissions/rules/") && init?.method === "DELETE") {
      made.push(`undo ${path}`);
      listed = [row(7, "mail -s hi me@x.com"), row(8, "mail -s again me@x.com")];
      return { ok: true };
    }
    return { ok: true };
  }) as never);
  return made;
}

describe("the Inbox holds what moves, whatever moved it", () => {
  it("(d) the waiting section coming back as its error notice alone holds the rows it pushed down", async () => {
    let pending: unknown[] = [ask("a")];
    const made = serve(() => pending, async () => {               // a refusal that comes back slowly: the card had expired meanwhile
      pending = [];
      await new Promise((r) => setTimeout(r, 900));
      throw new ApiError("no such pending card (answered or expired)", 404);
    });
    show();
    await settle(600);
    fireEvent.click(screen.getByTestId("runcmd-run"));
    await settle(950);                                               // the refusal is in: the section is back, as the notice alone
    expect(screen.getByTestId("inbox-approvals")).toBeInTheDocument();
    expect(screen.queryByTestId("runcmd-card")).toBeNull();
    fireEvent.click(within(rowAt(0)).getByTestId("inbox-refused-allow"));   // a click aimed at a row that has just moved
    await settle();
    expect(made).toEqual([]);
  });

  it("(u) when an Undo ends, the row that moves up into the allowed row's place is held", async () => {
    const made = serve(() => []);
    show();
    await settle(25_000);                                            // the list's next poll is at 30 s
    fireEvent.click(within(rowAt(0)).getByTestId("inbox-refused-allow"));   // allow row 7: its Undo is open until 35 s
    await settle(5_100);                                             // the 30 s poll no longer lists row 7; it stays in place for its Undo
    expect(screen.getAllByTestId("inbox-refused-row")).toHaveLength(2);
    await settle(5_000);                                             // 35.1 s: the Undo is over, row 7 leaves, row 8 moves up
    expect(screen.getAllByTestId("inbox-refused-row")).toHaveLength(1);
    fireEvent.click(within(rowAt(0)).getByTestId("inbox-refused-allow"));   // a click aimed at Undo, a moment too late
    await settle();
    expect(made).toEqual(["allow 7"]);
  });

  it("(s) the second click of a double-click on Always allow does not take the Undo that came up in its place", async () => {
    const made = serve(() => []);
    show();
    await settle(600);
    fireEvent.click(within(rowAt(0)).getByTestId("inbox-refused-allow"));   // click 1: the rule is made, Undo comes up in the same place
    await settle(30);
    fireEvent.click(within(rowAt(0)).getByTestId("inbox-refused-undo"));    // click 2
    await settle();
    expect(made).toEqual(["allow 7"]);
  });

  it("(s) the second click of a double-click on Undo does not take the Always allow that came back in its place", async () => {
    const made = serve(() => []);
    show();
    await settle(600);
    fireEvent.click(within(rowAt(0)).getByTestId("inbox-refused-allow"));
    await settle(600);
    fireEvent.click(within(rowAt(0)).getByTestId("inbox-refused-undo"));    // click 1: undone, "Always allow" is back in the same place
    await settle(30);
    fireEvent.click(within(rowAt(0)).getByTestId("inbox-refused-allow"));   // click 2
    await settle();
    expect(made).toEqual(["allow 7", "undo /permissions/rules/907"]);
  });

  it("nothing is held for good: 500 ms after each change the same buttons answer", async () => {
    const made = serve(() => []);
    show();
    await settle(600);
    fireEvent.click(within(rowAt(0)).getByTestId("inbox-refused-allow"));
    await settle(600);
    fireEvent.click(within(rowAt(0)).getByTestId("inbox-refused-undo"));
    await settle(600);
    fireEvent.click(within(rowAt(0)).getByTestId("inbox-refused-allow"));
    await settle();
    expect(made).toEqual(["allow 7", "undo /permissions/rules/907", "allow 7"]);
  });
});
