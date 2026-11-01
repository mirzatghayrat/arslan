/** INB5b-3 (v0.1.64), part 3: everything that waits on you has a row that is on screen and says why, as #590's "Not covered" asked.
 *  A project with a waiting conversation is listed in the sidebar even when it is not among the eight most recent; and a waiting row
 *  tells a card (a decision) from a stopped job's reminder (an offer), which otherwise hides the job's own outcome. */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { resolvedLanguage: "en", language: "en" } }) }));
vi.mock("../components/companion/BackgroundJobs", () => ({ default: () => null }));

import ConversationGlyph from "../components/ConversationGlyph";
import Sidebar, { SIDEBAR_PROJECTS } from "../components/Sidebar";
import { metaFrom } from "../lib/conversationMeta";

afterEach(cleanup);

const props = {
  activeThreadId: "", onSelectThread: () => {}, onAddThread: () => {}, activeSection: "arslan" as const,
  onChangeSection: () => {}, onArchiveThread: vi.fn(), onUnarchiveThread: vi.fn(), onDeleteThread: vi.fn(),
  backendStatus: "online" as const,
};

describe("every project with something waiting has a row in the sidebar", () => {
  it("lists a waiting project beyond the most recent ones, and not a quiet one beside it", () => {
    const count = SIDEBAR_PROJECTS + 2;
    const projects = Array.from({ length: count }, (_, i) => ({ id: `p${i}`, name: `Project ${i}` }));
    const threads = projects.map((p, i) => ({ id: `t${i}`, title: `T${i}`, projectId: p.id }));
    // One conversation per project, the first the newest: the last two projects are past the sidebar's few, and the last one waits.
    const meta = Object.fromEntries(threads.map((thread, i) => [thread.id, {
      kind: "chat", state: i === count - 1 ? "waiting" : "idle", origin: "mac", files: 0, projectId: thread.projectId,
      lastAt: new Date(Date.UTC(2026, 10, 1, 12) - i * 3_600_000).toISOString(),
    }]));
    render(<Sidebar {...props} threads={threads} projects={projects} meta={meta as never} />);
    expect(screen.getByTestId(`sidebar-project-p${SIDEBAR_PROJECTS - 1}`)).toBeTruthy();          // the last of the most recent
    expect(screen.queryByTestId(`sidebar-project-p${SIDEBAR_PROJECTS}`)).toBeNull();               // past them, quiet
    expect(screen.getByTestId(`sidebar-project-p${count - 1}`)).toBeTruthy();                       // past them, waiting
    expect(screen.getByTestId(`project-state-p${count - 1}`)).toHaveAttribute("aria-label", "sidebar.glyph.waiting");
  });
});

describe("a waiting row says what it waits on", () => {
  it("a card reads as waiting for your approval, an away entry as not asked while you were away, a stopped job's reminder as a reminder", () => {
    const meta = metaFrom([
      { conversation_id: "a", kind: "chat", state: "waiting", waiting_on: "card" },
      { conversation_id: "b", kind: "task", state: "waiting", waiting_on: "reminder" },
      { conversation_id: "c", kind: "chat", state: "waiting" },                       // an older server: no reason given
      { conversation_id: "d", kind: "chat", state: "idle", waiting_on: "reminder" },  // not waiting: the reason means nothing
      { conversation_id: "e", kind: "chat", state: "waiting", waiting_on: "away" },
      { conversation_id: "f", kind: "chat", state: "waiting", waiting_on: "later" },  // a reason this window does not know: a card
    ] as never);
    const ids = ["a", "b", "c", "d", "e", "f"];
    expect(ids.map((id) => meta[id].waitingOn)).toEqual(["card", "reminder", undefined, undefined, "away", undefined]);
    render(<>{ids.map((id) => <ConversationGlyph key={id} meta={meta[id]} />)}</>);
    expect(screen.getAllByRole("img", { name: "sidebar.glyph.waiting" })).toHaveLength(3);            // a, c and f
    expect(screen.getAllByRole("img", { name: "sidebar.glyph.waiting_reminder" })).toHaveLength(1);
    // ⓪Plan's review of PR 614, N2: nothing is left to approve, so it says so; it keeps the card's amber "!" (no new mark to learn).
    expect(screen.getByRole("img", { name: "sidebar.glyph.waiting_away" }).textContent).toBe("!");
  });
});

describe("a project row says what its waiting conversations wait on", () => {
  it("shows the bell only when every waiting conversation under it waits on a reminder; else a card wins, then an away entry", () => {
    // ⓪Plan's review of PR 614, N1: a project whose only waiting conversation is a reminder read "Waiting for your approval".
    const rows = [
      ["t1", "p1", "waiting", "reminder"], ["t2", "p1", "idle", undefined],         // a reminder, and a quiet conversation
      ["t3", "p2", "waiting", "reminder"], ["t4", "p2", "waiting", "card"],          // a reminder and a card
      ["t5", "p3", "waiting", "reminder"], ["t6", "p3", "waiting", "away"],          // a reminder and an away entry
      ["t7", "p4", "waiting", "reminder"], ["t8", "p4", "waiting", undefined],       // a reminder and an older server's waiting row
      ["t9", "p5", "waiting", "away"], ["t10", "p5", "waiting", "card"],             // an away entry and a card
    ] as const;
    const projects = ["p1", "p2", "p3", "p4", "p5"].map((id) => ({ id, name: id }));
    const threads = rows.map(([id, projectId]) => ({ id, title: id, projectId }));
    const meta = Object.fromEntries(rows.map(([id, projectId, state, waitingOn]) =>
      [id, { kind: "chat", state, origin: "mac", files: 0, projectId, ...(waitingOn ? { waitingOn } : {}) }]));
    render(<Sidebar {...props} threads={threads} projects={projects} meta={meta as never} />);
    const row = (p: string) => screen.getByTestId(`project-state-${p}`);
    expect(projects.map(({ id }) => row(id).getAttribute("aria-label"))).toEqual(["sidebar.glyph.waiting_reminder",
      "sidebar.glyph.waiting", "sidebar.glyph.waiting_away", "sidebar.glyph.waiting", "sidebar.glyph.waiting"]);
    // What is drawn agrees with the label: the bell, else the "!".
    expect(row("p1").querySelector(".lucide-bell")).toBeTruthy();
    for (const p of ["p2", "p3", "p4", "p5"]) {
      expect(row(p).querySelector(".lucide-bell")).toBeNull();
      expect(within(row(p)).getByText("!")).toBeTruthy();
    }
  });
});
