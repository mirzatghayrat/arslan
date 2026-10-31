/** INB5b-3 (v0.1.64), part 3: everything that waits on you has a row that is on screen, as #590's "Not covered" asked. A project with
 *  a waiting conversation is listed in the sidebar even when it is not among the eight most recent. */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { resolvedLanguage: "en", language: "en" } }) }));
vi.mock("../components/companion/BackgroundJobs", () => ({ default: () => null }));

import Sidebar, { SIDEBAR_PROJECTS } from "../components/Sidebar";

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
