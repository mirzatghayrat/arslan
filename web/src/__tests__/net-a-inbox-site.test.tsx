/** NET-a, Codex round 1 F7: an entry of NET-a's card in the list of what could not be asked (a site the proxy refused where
 *  nobody could be asked, or a card that never opened) offers that card's "In this conversation" for the sites the server
 *  lists. The click sends the entry's id and nothing else, says what it allowed, and Undo deletes exactly the grants the
 *  server made. The words are the card's own and the Remembered answers page's, in every language. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import * as client from "../api/client";
import NotDoneList from "../components/proactive/NotDoneList";
import { isolate } from "../lib/outsideText";
import { ANSWER_GUARD_MS } from "../components/kit";
import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import es from "../locales/es.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
/** A list that has just appeared, or a button that came up where another was, answers 500 ms later (kit/guard.ts). */
const pastGuard = () => act(async () => { await new Promise((r) => setTimeout(r, ANSWER_GUARD_MS + 30)); });

// As GET /approvals/refused sends one (server/api/approvals.py): `sites`, what "In this conversation" allows.
const site = { id: 50, created_at: "2026-11-14T09:00:00Z", first_at: "2026-11-14T09:00:00Z", count: 1, conversation_id: "c1",
  kind: "network", target: "network:collect.evil.example",
  detail: "`curl -s https://collect.evil.example/in` tried to connect to collect.evil.example, a site that appeared only in outside content",
  always_ok: false, always: [], unattended: false, unopened: true, sites: ["collect.evil.example"] };

function serve(rows: unknown[], post: () => unknown = () => ({ grants: [{ id: 701, target: "network:collect.evil.example" }] })) {
  return vi.spyOn(client, "request").mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.startsWith("/approvals/refused")) return rows as never;
    if (init?.method === "POST") return post() as never;
    return {} as never;
  });
}
const row = (n = 0) => screen.getAllByTestId("inbox-refused-row")[n];

describe("NET-a: a refused site's In this conversation, from the list", () => {
  it("offers its card's In this conversation for the sites listed, and no Always", async () => {
    serve([site]);
    render(<NotDoneList conversationId="c1" awayOnly />);
    await screen.findAllByTestId("inbox-refused-row");
    expect(within(row()).getByTestId("inbox-refused-allow-here"))
      .toHaveTextContent(`kit.scope.conversationFor:${JSON.stringify({ label: isolate("collect.evil.example") })}`);
    expect(within(row()).queryByTestId("inbox-refused-allow")).toBeNull();
    expect(within(row()).queryByTestId("inbox-refused-each-time")).toBeNull();
  });

  it("sends the entry's id and nothing else, says what it allowed, and Undo deletes exactly those grants", async () => {
    const req = serve([site]);
    render(<NotDoneList conversationId="c1" awayOnly />);
    await screen.findAllByTestId("inbox-refused-row");
    await pastGuard();
    fireEvent.click(within(row()).getByTestId("inbox-refused-allow-here"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/permissions/grants",
      { method: "POST", body: JSON.stringify({ refused_id: 50 }) }));
    expect(await within(row()).findByTestId("inbox-refused-allowed"))
      .toHaveTextContent(`remembered.grant.other:${JSON.stringify({ name: isolate("collect.evil.example") })}`);
    expect(req.mock.calls.some(([path]) => String(path).startsWith("/permissions/rules"))).toBe(false);
    await pastGuard();                                                  // Undo came up where the button was
    fireEvent.click(within(row()).getByTestId("inbox-refused-undo"));
    await waitFor(() => expect(req).toHaveBeenCalledWith("/permissions/grants/701", { method: "DELETE" }));
  });

  it("a scheduled run's entry says beside it that the run itself never takes the step (S1)", async () => {
    serve([{ ...site, unattended: true, unopened: undefined }]);
    render(<NotDoneList conversationId="scheduled-1" unattended />);
    await screen.findAllByTestId("inbox-refused-row");
    expect(within(row()).getByTestId("inbox-refused-unattended")).toHaveTextContent("inbox.scheduledNeverAsks");
    expect(within(row()).getByTestId("inbox-refused-allow-here")).toBeInTheDocument();
  });

  it("an entry with no site left to allow, or from an older server, offers no such button", async () => {
    serve([{ ...site, sites: [] }, { ...site, id: 51, target: "network:drop.evil.example", sites: undefined }]);
    render(<NotDoneList conversationId="c1" awayOnly />);
    await screen.findAllByTestId("inbox-refused-row");
    expect(screen.queryByTestId("inbox-refused-allow-here")).toBeNull();
    expect(screen.getAllByTestId("inbox-refused-each-time")).toHaveLength(2);
  });

  it("a 409 (nothing to allow after all) says it asks each time", async () => {
    serve([site], () => { throw new client.ApiError("no_site", 409, { code: "no_site" }); });
    render(<NotDoneList conversationId="c1" awayOnly />);
    await screen.findAllByTestId("inbox-refused-row");
    await pastGuard();
    fireEvent.click(within(row()).getByTestId("inbox-refused-allow-here"));
    expect(await within(row()).findByTestId("inbox-refused-each-time")).toHaveTextContent("inbox.asksEachTime");
    expect(within(row()).queryByTestId("inbox-refused-allow-here")).toBeNull();
  });

  it("the words it reuses are there in every language", () => {
    type Words = { kit: { scope: Record<string, string> }; remembered: { grant: Record<string, string> } };
    for (const [lang, words] of Object.entries({ en, zh, ja, es, de, fr }) as [string, Words][]) {
      expect(words.kit.scope.conversationFor, lang).toContain("{{label}}");
      expect(words.remembered.grant.other, lang).toContain("{{name}}");
    }
  });
});
