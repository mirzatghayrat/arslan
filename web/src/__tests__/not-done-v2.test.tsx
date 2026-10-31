/** 0.1.61 §A4: "Not done while you were away", moved from inbox-v2.test.tsx when the Inbox went (INB5b-2). The list (NotDoneList) now sits
 *  in a conversation and on the Scheduled page. The file's "Approve now" half answered cards over HTTP as the Inbox; the window answers them
 *  in the ask slot, covered by card-answer-by-id, card-v2 and card-choices (the Island keeps its own HTTP answer, island-ask). */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import * as client from "../api/client";
import NotDoneList from "../components/proactive/NotDoneList";
import { isolate } from "../lib/outsideText";
import { formatUiDateTime } from "../lib/localeFormatting";
import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import es from "../locales/es.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";
import { ANSWER_GUARD_MS } from "../components/kit";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
/** One gesture answers one thing (kit/guard.ts): a card or a list that has just appeared, comes up after another left, or is paged to,
 *  answers 500 ms later. */
const pastGuard = () => act(async () => { await new Promise((r) => setTimeout(r, ANSWER_GUARD_MS + 30)); });

const ask = {
  call_id: "c1", conversation_id: "conv-9", opened_at: 1000, expires_at: 1300,
  frame: { type: "propose_run_command", call_id: "c1", pretty: "git push", reason: "pushes to a remote" },
};

describe("Not done while you were away", () => {
  // As GET /approvals/refused sends them (server/api/approvals.py): one entry per kind and target, newest
  // first, times in UTC with a Z; `always` is what "Always allow" will store, in the words its card used.
  const mail = { id: 30, created_at: "2026-10-12T09:00:00Z", first_at: "2026-10-12T07:00:00Z", count: 4,
    conversation_id: "c", kind: "command", target: "rules:send-mail", detail: "mail -s hi me@x.com", always_ok: true,
    always: [{ kind: "legacy_rule", target: "send-mail", label: "Send an email" }] };
  const write = { id: 21, created_at: "2026-10-12T08:00:00Z", first_at: "2026-10-12T08:00:00Z", count: 1,
    conversation_id: "c", kind: "workspace_write", target: "/Users/me/Notes", detail: "plan.md", always_ok: false, always: [] };
  const when = (iso: string) => formatUiDateTime(iso).replace(/\s+/g, " ");      // as the page prints it
  function serve(rows: unknown[] = [mail, write], post: (body: string) => unknown = () => ({ id: 9 })) {
    return vi.spyOn(client, "request").mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/approvals/refused?hours=24") return rows as never;
      if (path === "/permissions/rules" && init?.method === "POST") return post(String(init.body)) as never;
      return [] as never;
    });
  }
  const row = (n: number) => screen.getAllByTestId("inbox-refused-row")[n];

  it("lists each entry once with how many times and since when, and says what Always allow will store", async () => {
    const count = vi.fn();
    serve();
    render(<NotDoneList onCount={count} />);
    await screen.findAllByTestId("inbox-refused-row");
    await pastGuard();                                                  // a list that has just appeared is clicked 500 ms later
    expect(row(0)).toHaveTextContent("mail -s hi me@x.com");                  // the command, not "rules:send-mail"
    expect(row(0)).not.toHaveTextContent("rules:send-mail");
    expect(row(0)).toHaveTextContent(`inbox.refusedTimes:${JSON.stringify({ count: 4, since: when("2026-10-12T07:00:00Z") })}`);
    expect(within(row(0)).getByTestId("inbox-refused-stores")).toHaveTextContent(`inbox.alwaysStores:${JSON.stringify({ what: isolate("Send an email") })}`);
    expect(row(1)).toHaveTextContent(when("2026-10-12T08:00:00Z"));           // once: its time, no count
    expect(row(1)).not.toHaveTextContent("inbox.refusedTimes");
    expect(count).toHaveBeenLastCalledWith(2);
  });

  it("Always allow sends the entry's id and nothing else, then reads Allowed from now on", async () => {
    const req = serve();
    render(<NotDoneList />);
    await screen.findAllByTestId("inbox-refused-row");
    await pastGuard();                                                  // a list that has just appeared is clicked 500 ms later
    fireEvent.click(within(row(0)).getByTestId("inbox-refused-allow"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/permissions/rules",
      { method: "POST", body: JSON.stringify({ refused_id: 30 }) }));
    expect(await within(row(0)).findByTestId("inbox-refused-allowed")).toHaveTextContent("inbox.allowedNow");
    expect(within(row(0)).queryByTestId("inbox-refused-stores")).toBeNull();            // answered: no longer a question
  });

  it("offers the click only for an entry whose card would have offered Always; the rest read Asks each time", async () => {
    serve();
    render(<NotDoneList />);
    await screen.findAllByTestId("inbox-refused-row");
    await pastGuard();                                                  // a list that has just appeared is clicked 500 ms later
    expect(screen.getAllByTestId("inbox-refused-allow")).toHaveLength(1);
    expect(within(row(1)).queryByTestId("inbox-refused-allow")).toBeNull();
    expect(within(row(1)).queryByTestId("inbox-refused-stores")).toBeNull();
    expect(within(row(1)).getByTestId("inbox-refused-each-time")).toHaveTextContent("inbox.asksEachTime");
  });

  it("a scheduled run's refusal says why nothing can be allowed, beside an away card for the same thing (S1)", async () => {
    serve([mail, { ...mail, id: 29, always_ok: false, always: [], unattended: true }]);
    render(<NotDoneList />);
    await screen.findAllByTestId("inbox-refused-row");
    await pastGuard();
    expect(screen.getAllByTestId("inbox-refused-row")).toHaveLength(2);
    expect(within(row(0)).getByTestId("inbox-refused-allow")).toBeInTheDocument();
    expect(within(row(1)).queryByTestId("inbox-refused-allow")).toBeNull();
    expect(within(row(1)).getByTestId("inbox-refused-each-time")).toHaveTextContent("inbox.scheduledNeverAsks");
  });

  it("an entry whose card would not have offered Always gets no click even if a list came with it", async () => {
    serve([{ ...mail, always_ok: false }]);
    render(<NotDoneList />);
    await screen.findAllByTestId("inbox-refused-row");
    await pastGuard();                                                  // a list that has just appeared is clicked 500 ms later
    expect(screen.queryByTestId("inbox-refused-allow")).toBeNull();
    expect(screen.queryByTestId("inbox-refused-stores")).toBeNull();
    expect(within(row(0)).getByTestId("inbox-refused-each-time")).toHaveTextContent("inbox.asksEachTime");
  });

  it("never offers a click it cannot show the result of: Always allowed with nothing listed to store reads Asks each time", async () => {
    // The server sends `always` empty exactly when always_ok is false; if the two ever disagree, the person must not be asked to agree to nothing.
    serve([{ ...mail, always: [] }]);
    render(<NotDoneList />);
    await screen.findAllByTestId("inbox-refused-row");
    await pastGuard();                                                  // a list that has just appeared is clicked 500 ms later
    expect(screen.queryByTestId("inbox-refused-allow")).toBeNull();
    expect(screen.queryByTestId("inbox-refused-stores")).toBeNull();
    expect(within(row(0)).getByTestId("inbox-refused-each-time")).toHaveTextContent("inbox.asksEachTime");
  });

  it("says every rule Always allow will store, each in the words its card used, and the click sends the id only", async () => {
    const both = { ...mail, always: [{ kind: "legacy_rule", target: "send-mail", label: "Send an email" },
                                     { kind: "app", target: "com.apple.Mail", label: "Mail" }] };
    const req = serve([both]);
    render(<NotDoneList />);
    await screen.findAllByTestId("inbox-refused-row");
    await pastGuard();                                                  // a list that has just appeared is clicked 500 ms later
    expect(within(row(0)).getAllByTestId("inbox-refused-rule").map((r) => r.textContent)).toEqual(
      ["Send an email", "Mail"].map((name) => `inbox.alwaysStores:${JSON.stringify({ what: isolate(name) })}`));     // each rule on a line of its own
    fireEvent.click(within(row(0)).getByTestId("inbox-refused-allow"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/permissions/rules", { method: "POST", body: JSON.stringify({ refused_id: 30 }) }));
  });

  it("a rule with no label is shown by its target, never as nothing", async () => {
    serve([{ ...mail, always: [{ kind: "legacy_rule", target: "send-mail", label: "" }] }]);
    render(<NotDoneList />);
    await screen.findAllByTestId("inbox-refused-row");
    await pastGuard();                                                  // a list that has just appeared is clicked 500 ms later
    expect(within(row(0)).getByTestId("inbox-refused-stores")).toHaveTextContent(`inbox.alwaysStores:${JSON.stringify({ what: isolate("send-mail") })}`);
  });

  it("a 409 (nothing to allow after all) says it asks each time", async () => {
    serve([mail], () => { throw new client.ApiError("no_always", 409, { code: "no_always" }); });
    render(<NotDoneList />);
    await screen.findAllByTestId("inbox-refused-row");
    await pastGuard();                                                  // a list that has just appeared is clicked 500 ms later
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    expect(await screen.findByTestId("inbox-refused-each-time")).toHaveTextContent("inbox.asksEachTime");
    expect(screen.queryByTestId("inbox-refused-allow")).toBeNull();
    expect(screen.queryByTestId("inbox-refused-allowed")).toBeNull();
  });

  it("a 404 (the entry has gone) reloads the list", async () => {
    const req = serve([mail], () => { throw new client.ApiError("no such refusal", 404); });
    render(<NotDoneList />);
    await screen.findAllByTestId("inbox-refused-row");
    await pastGuard();                                                  // a list that has just appeared is clicked 500 ms later
    const lists = () => req.mock.calls.filter(([path]) => path === "/approvals/refused?hours=24").length;
    expect(lists()).toBe(1);
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await waitFor(() => expect(lists()).toBe(2));
    expect(screen.queryByTestId("inbox-refused-allowed")).toBeNull();
  });

  it("an older server (no list) shows nothing and tells the Inbox nothing", async () => {
    vi.spyOn(client, "request").mockRejectedValue(new client.ApiError("Not Found", 404));
    const count = vi.fn();
    const { container } = render(<NotDoneList onCount={count} />);
    await new Promise((r) => setTimeout(r, 10));
    expect(container).toBeEmptyDOMElement();
    expect(count).not.toHaveBeenCalled();
  });

  it("no word of the section calls what was not asked declined or refused, in any language", () => {
    // An away entry is an expiry: nobody said no. (The mock above shows keys, so this reads the words.)
    const NO: Record<string, RegExp> = {
      en: /declin|refus|reject|den(y|ied)/i, zh: /拒绝/, ja: /拒否/, es: /rechaz|deneg/i, de: /ablehn|verweiger/i, fr: /refus|rejet/i,
    };
    const keys = ["refusedTitle", "alwaysAllow", "alwaysStores", "asksEachTime", "allowedNow", "refusedTimes", "undo"];
    for (const [lang, words] of Object.entries({ en, zh, ja, es, de, fr }) as [string, { inbox: Record<string, string> }][]) {
      for (const key of keys) {
        expect(words.inbox[key], `${lang} inbox.${key}`).toBeTypeOf("string");
        expect(words.inbox[key].trim().length, `${lang} inbox.${key}`).toBeGreaterThan(0);
        expect(words.inbox[key], `${lang} inbox.${key}`).not.toMatch(NO[lang]);
      }
    }
  });
});
