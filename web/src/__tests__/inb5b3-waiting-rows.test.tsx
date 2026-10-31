/** INB5b-3 (v0.1.64), part 3: everything that waits on you has a row that is on screen and says why, as #590's "Not covered" asked.
 *  A project with a waiting conversation is listed in the sidebar even when it is not among the eight most recent; and a waiting row
 *  tells a card (a decision) from a stopped job's reminder (an offer), which otherwise hides the job's own outcome. */
import { cleanup, render, screen } from "@testing-library/react";
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
  it("a card reads as waiting for your approval, a stopped job's reminder as a reminder, from the server's waiting_on", () => {
    const meta = metaFrom([
      { conversation_id: "a", kind: "chat", state: "waiting", waiting_on: "card" },
      { conversation_id: "b", kind: "task", state: "waiting", waiting_on: "reminder" },
      { conversation_id: "c", kind: "chat", state: "waiting" },                       // an older server: no reason given
      { conversation_id: "d", kind: "chat", state: "idle", waiting_on: "reminder" },  // not waiting: the reason means nothing
    ] as never);
    expect([meta.a.waitingOn, meta.b.waitingOn, meta.c.waitingOn, meta.d.waitingOn]).toEqual(["card", "reminder", undefined, undefined]);
    render(<>{["a", "b", "c", "d"].map((id) => <ConversationGlyph key={id} meta={meta[id]} />)}</>);
    expect(screen.getAllByRole("img", { name: "sidebar.glyph.waiting" })).toHaveLength(2);
    expect(screen.getAllByRole("img", { name: "sidebar.glyph.waiting_reminder" })).toHaveLength(1);
  });
});
