/** 0.1.61 §A4 (PR 2b final re-review), moved from inbox-holds-what-moves.test.tsx when the Inbox went (INB5b-2): one gesture answers one
 *  thing in "Not done while you were away" (NotDoneList), also when a row moves for a reason that is not a new list from the server.
 *  (u) A row allowed a moment ago stays in its place while its ten-second Undo is open, even when the server no longer lists it. When the Undo
 *      ends, or is pressed, that row leaves and the rows below move up: the second click of a double-click on Undo must not become an
 *      "Always allow" on the row that moved into its place.
 *  The Inbox's case (d), its waiting section coming back as an error notice, went with the Inbox's layout. */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import * as client from "../api/client";
import { ApiError } from "../api/client";
import NotDoneList from "../components/proactive/NotDoneList";


beforeEach(() => {
  void i18n.changeLanguage("en");
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-13T10:00:00Z"));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
// React draws what one act schedules only when the act ends: a step at a time, so each change is drawn when it comes.
const settle = async (ms = 0) => { for (let t = 0; t < ms; t += 50) await act(async () => { await vi.advanceTimersByTimeAsync(Math.min(50, ms - t)); });
  await act(async () => { await vi.advanceTimersByTimeAsync(0); }); };

const row = (id: number, detail: string) => ({ id, created_at: "2026-10-13T09:00:00Z", first_at: "2026-10-13T09:00:00Z", count: 1, conversation_id: "c",
  kind: "command", target: `rules:${id}`, detail, always_ok: true, always: [{ kind: "legacy_rule", target: `r${id}`, label: `rule ${id}` }] });
const show = () => render(<NotDoneList />);
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

describe("Not done while you were away holds what moves, whatever moved it", () => {
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
