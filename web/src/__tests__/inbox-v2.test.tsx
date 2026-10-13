/** 0.1.55 §12: the Inbox is everything waiting for the user's decision — cards to
 *  approve (answered here, over HTTP), and memory waiting for an OK (three sources, one list). */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import * as client from "../api/client";
import { companionApi } from "../api/companion";
import { lessonsApi } from "../api/lessons";
import InboxApprovals from "../components/proactive/InboxApprovals";
import InboxMemory from "../components/proactive/InboxMemory";
import InboxRefused from "../components/proactive/InboxRefused";
import { formatUiDateTime } from "../lib/localeFormatting";
import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import es from "../locales/es.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";
import { loadPendingMemory } from "../lib/pendingMemory";
import { ANSWER_GUARD_MS } from "../components/kit";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const ask = {
  call_id: "c1", conversation_id: "conv-9", opened_at: 1000, expires_at: 1300,
  frame: { type: "propose_run_command", call_id: "c1", pretty: "git push", reason: "pushes to a remote" },
};

describe("Approve now", () => {
  it("lists a waiting card from any conversation and answers it over HTTP, as the Inbox", async () => {
    const req = vi.spyOn(client, "request").mockImplementation(async (path: string) =>
      (path === "/approvals/pending" ? [ask] : { ok: true }) as never);
    const opened = vi.fn();
    render(<InboxApprovals onOpenConversation={opened} />);
    expect(await screen.findByTestId("runcmd-card")).toBeInTheDocument();
    expect(screen.getByTestId("ask-risk")).toHaveTextContent("pushes to a remote");
    fireEvent.click(screen.getByText("kit.seeContext"));
    expect(opened).toHaveBeenCalledWith("conv-9");
    fireEvent.click(screen.getByTestId("runcmd-run"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/c1/answer",
      { method: "POST", body: JSON.stringify({ approve: true, source: "inbox" }) }));
  });

  it("a card it cannot answer outside the chat is not shown; nothing waiting shows nothing", async () => {
    vi.spyOn(client, "request").mockResolvedValue([{ ...ask, frame: { type: "propose_connect_mcp", call_id: "m" } }] as never);
    const count = vi.fn();
    const { container } = render(<InboxApprovals onOpenConversation={() => {}} onCount={count} />);
    await waitFor(() => expect(count).toHaveBeenCalledWith(0));
    expect(container).toBeEmptyDOMElement();
  });
});

/** One gesture answers one card (kit/guard.ts): the card that comes up after another left, or is paged to, answers 500 ms later. */
const pastGuard = () => act(async () => { await new Promise((r) => setTimeout(r, ANSWER_GUARD_MS + 30)); });

describe("Approve now — a card from the permission layer (0.1.61 §A4)", () => {
  const v2 = { call_id: "k1", conversation_id: "conv-9", opened_at: 1000, expires_at: 2800,
    frame: { type: "propose_action", call_id: "k1", kind: "app", target: "com.apple.Notes", detail: "", title: "Use Notes?",
             options: ["task", "conversation", "always"], always_label: "Notes", perm_kind: "app" } };

  it("offers the card's choices and posts the one chosen", async () => {
    const req = vi.spyOn(client, "request").mockImplementation(async (path: string) =>
      (path === "/approvals/pending" ? [v2] : { ok: true }) as never);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    fireEvent.click(await screen.findByTestId("action-scope-conversation"));
    fireEvent.click(screen.getByTestId("action-allow"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/k1/answer",
      { method: "POST", body: JSON.stringify({ approve: true, source: "inbox", scope: "conversation" }) }));
  });

  it("No with a note posts the note; a plain No posts none", async () => {
    const req = vi.spyOn(client, "request").mockImplementation(async (path: string) =>
      (path === "/approvals/pending" ? [v2, { ...v2, call_id: "k2", frame: { ...v2.frame, call_id: "k2" } }] : { ok: true }) as never);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    fireEvent.click(await screen.findByText("kit.noteLink"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "use Bear" } });
    fireEvent.click(screen.getByText("kit.noteSend"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/k1/answer",
      { method: "POST", body: JSON.stringify({ approve: false, source: "inbox", note: "use Bear" }) }));
    await pastGuard();                                                  // k2 moved up under the pointer: it answers 500 ms later
    fireEvent.click(await screen.findByTestId("action-deny"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/k2/answer",
      { method: "POST", body: JSON.stringify({ approve: false, source: "inbox" }) }));
  });

  it("a choice made on one card is not carried to the next one in the queue", async () => {
    const req = vi.spyOn(client, "request").mockImplementation(async (path: string) =>
      (path === "/approvals/pending" ? [v2, { ...v2, call_id: "k2", frame: { ...v2.frame, call_id: "k2" } }] : { ok: true }) as never);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    fireEvent.click(await screen.findByTestId("action-scope-always"));
    fireEvent.click(screen.getByLabelText("kit.next"));
    expect((screen.getByTestId("action-scope-task") as HTMLInputElement).checked).toBe(true);
    await pastGuard();                                                  // a card paged to answers 500 ms later
    fireEvent.click(screen.getByTestId("action-allow"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/approvals/k2/answer",
      { method: "POST", body: JSON.stringify({ approve: true, source: "inbox", scope: "task" }) }));
  });

  it("an old command card in the Inbox offers no 'remember' tick: the server never keeps it there", async () => {
    vi.spyOn(client, "request").mockImplementation(async (path: string) =>
      (path === "/approvals/pending" ? [{ ...ask, frame: { ...ask.frame, sandbox: "retry" } }] : { ok: true }) as never);
    render(<InboxApprovals onOpenConversation={() => {}} />);
    expect(await screen.findByTestId("runcmd-card")).toBeInTheDocument();
    expect(screen.queryByTestId("runcmd-remember")).toBeNull();
  });
});

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
    render(<InboxRefused onCount={count} />);
    await screen.findAllByTestId("inbox-refused-row");
    expect(row(0)).toHaveTextContent("mail -s hi me@x.com");                  // the command, not "rules:send-mail"
    expect(row(0)).not.toHaveTextContent("rules:send-mail");
    expect(row(0)).toHaveTextContent(`inbox.refusedTimes:${JSON.stringify({ count: 4, since: when("2026-10-12T07:00:00Z") })}`);
    expect(within(row(0)).getByTestId("inbox-refused-stores")).toHaveTextContent('inbox.alwaysStores:{"what":"Send an email"}');
    expect(row(1)).toHaveTextContent(when("2026-10-12T08:00:00Z"));           // once: its time, no count
    expect(row(1)).not.toHaveTextContent("inbox.refusedTimes");
    expect(count).toHaveBeenLastCalledWith(2);
  });

  it("Always allow sends the entry's id and nothing else, then reads Allowed from now on", async () => {
    const req = serve();
    render(<InboxRefused />);
    await screen.findAllByTestId("inbox-refused-row");
    fireEvent.click(within(row(0)).getByTestId("inbox-refused-allow"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/permissions/rules",
      { method: "POST", body: JSON.stringify({ refused_id: 30 }) }));
    expect(await within(row(0)).findByTestId("inbox-refused-allowed")).toHaveTextContent("inbox.allowedNow");
    expect(within(row(0)).queryByTestId("inbox-refused-stores")).toBeNull();            // answered: no longer a question
  });

  it("offers the click only for an entry whose card would have offered Always; the rest read Asks each time", async () => {
    serve();
    render(<InboxRefused />);
    await screen.findAllByTestId("inbox-refused-row");
    expect(screen.getAllByTestId("inbox-refused-allow")).toHaveLength(1);
    expect(within(row(1)).queryByTestId("inbox-refused-allow")).toBeNull();
    expect(within(row(1)).queryByTestId("inbox-refused-stores")).toBeNull();
    expect(within(row(1)).getByTestId("inbox-refused-each-time")).toHaveTextContent("inbox.asksEachTime");
  });

  it("an entry whose card would not have offered Always gets no click even if a list came with it", async () => {
    serve([{ ...mail, always_ok: false }]);
    render(<InboxRefused />);
    await screen.findAllByTestId("inbox-refused-row");
    expect(screen.queryByTestId("inbox-refused-allow")).toBeNull();
    expect(screen.queryByTestId("inbox-refused-stores")).toBeNull();
    expect(within(row(0)).getByTestId("inbox-refused-each-time")).toHaveTextContent("inbox.asksEachTime");
  });

  it("never offers a click it cannot show the result of: Always allowed with nothing listed to store reads Asks each time", async () => {
    // The server sends `always` empty exactly when always_ok is false; if the two ever disagree, the person must not be asked to agree to nothing.
    serve([{ ...mail, always: [] }]);
    render(<InboxRefused />);
    await screen.findAllByTestId("inbox-refused-row");
    expect(screen.queryByTestId("inbox-refused-allow")).toBeNull();
    expect(screen.queryByTestId("inbox-refused-stores")).toBeNull();
    expect(within(row(0)).getByTestId("inbox-refused-each-time")).toHaveTextContent("inbox.asksEachTime");
  });

  it("says every rule Always allow will store, each in the words its card used, and the click sends the id only", async () => {
    const both = { ...mail, always: [{ kind: "legacy_rule", target: "send-mail", label: "Send an email" },
                                     { kind: "app", target: "com.apple.Mail", label: "Mail" }] };
    const req = serve([both]);
    render(<InboxRefused />);
    await screen.findAllByTestId("inbox-refused-row");
    expect(within(row(0)).getByTestId("inbox-refused-stores")).toHaveTextContent('inbox.alwaysStores:{"what":"Send an email, Mail"}');
    fireEvent.click(within(row(0)).getByTestId("inbox-refused-allow"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/permissions/rules", { method: "POST", body: JSON.stringify({ refused_id: 30 }) }));
  });

  it("a rule with no label is shown by its target, never as nothing", async () => {
    serve([{ ...mail, always: [{ kind: "legacy_rule", target: "send-mail", label: "" }] }]);
    render(<InboxRefused />);
    await screen.findAllByTestId("inbox-refused-row");
    expect(within(row(0)).getByTestId("inbox-refused-stores")).toHaveTextContent('inbox.alwaysStores:{"what":"send-mail"}');
  });

  it("a 409 (nothing to allow after all) says it asks each time", async () => {
    serve([mail], () => { throw new client.ApiError("no_always", 409, { code: "no_always" }); });
    render(<InboxRefused />);
    await screen.findAllByTestId("inbox-refused-row");
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    expect(await screen.findByTestId("inbox-refused-each-time")).toHaveTextContent("inbox.asksEachTime");
    expect(screen.queryByTestId("inbox-refused-allow")).toBeNull();
    expect(screen.queryByTestId("inbox-refused-allowed")).toBeNull();
  });

  it("a 404 (the entry has gone) reloads the list", async () => {
    const req = serve([mail], () => { throw new client.ApiError("no such refusal", 404); });
    render(<InboxRefused />);
    await screen.findAllByTestId("inbox-refused-row");
    const lists = () => req.mock.calls.filter(([path]) => path === "/approvals/refused?hours=24").length;
    expect(lists()).toBe(1);
    fireEvent.click(screen.getByTestId("inbox-refused-allow"));
    await waitFor(() => expect(lists()).toBe(2));
    expect(screen.queryByTestId("inbox-refused-allowed")).toBeNull();
  });

  it("an older server (no list) shows nothing and tells the Inbox nothing", async () => {
    vi.spyOn(client, "request").mockRejectedValue(new client.ApiError("Not Found", 404));
    const count = vi.fn();
    const { container } = render(<InboxRefused onCount={count} />);
    await new Promise((r) => setTimeout(r, 10));
    expect(container).toBeEmptyDOMElement();
    expect(count).not.toHaveBeenCalled();
  });

  it("no word of the section calls what was not asked declined or refused, in any language", () => {
    // An away entry is an expiry: nobody said no. (The mock above shows keys, so this reads the words.)
    const NO: Record<string, RegExp> = {
      en: /declin|refus|reject|den(y|ied)/i, zh: /拒绝/, ja: /拒否/, es: /rechaz|deneg/i, de: /ablehn|verweiger/i, fr: /refus|rejet/i,
    };
    const keys = ["refusedTitle", "alwaysAllow", "alwaysStores", "asksEachTime", "allowedNow", "refusedTimes"];
    for (const [lang, words] of Object.entries({ en, zh, ja, es, de, fr }) as [string, { inbox: Record<string, string> }][]) {
      for (const key of keys) {
        expect(words.inbox[key], `${lang} inbox.${key}`).toBeTypeOf("string");
        expect(words.inbox[key], `${lang} inbox.${key}`).not.toMatch(NO[lang]);
      }
    }
  });
});

describe("memory waiting for your OK", () => {
  it("merges the three sources, and one failing source hides nothing else", async () => {
    vi.spyOn(companionApi, "proposals").mockResolvedValue([{ id: 1, target_id: "e1", target_version: 1, reason: "",
      candidate: null, entry: { content: "体检报告里的血压数据", sensitivity: "sensitive", created_at: "2026-10-06T00:00:00Z" } }] as never);
    vi.spyOn(client.api, "listMemoryProposals").mockRejectedValue(new Error("down"));
    vi.spyOn(lessonsApi, "list").mockResolvedValue([
      { id: 7, status: "proposed", text: "读大表格 → 先看表头", created_at: "2026-10-07T00:00:00Z" },
      { id: 8, status: "active", text: "not waiting", created_at: "2026-10-07T00:00:00Z" }] as never);
    const items = await loadPendingMemory(((k: string) => k) as never);
    expect(items.map((i) => [i.source, i.text, i.sensitive])).toEqual([
      ["lesson", "读大表格 → 先看表头", false], ["memory", "体检报告里的血压数据", true]]);
  });

  it("a sensitive one is kept for local models only, with the sensitivity acknowledged", async () => {
    vi.spyOn(companionApi, "proposals").mockResolvedValue([{ id: 3, target_id: "e3", target_version: 1, reason: "",
      candidate: null, entry: { content: "血压", sensitivity: "sensitive", created_at: "2026-10-06T00:00:00Z" } }] as never);
    vi.spyOn(client.api, "listMemoryProposals").mockResolvedValue([]);
    vi.spyOn(lessonsApi, "list").mockResolvedValue([]);
    const resolve = vi.spyOn(companionApi, "resolveProposal").mockResolvedValue({} as never);
    render(<InboxMemory />);
    fireEvent.click(await screen.findByText("pendingMemory.keepLocal"));
    await waitFor(() => expect(resolve).toHaveBeenCalledWith(3, true, true, false));
  });
});
