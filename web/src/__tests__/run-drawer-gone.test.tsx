/**
 * The run drawer is gone (the user, 2026-11-02: 「去掉」): its fleet radar and history sparkline went with it, and everything
 * else it offered is in the inspector's 「诊断」 (#631). A scheduled run, which opened the drawer, now opens on Progress, picked.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en", resolvedLanguage: "en" } }),
}));
vi.mock("../api/client", () => ({ request: vi.fn(), api: {} }));
vi.mock("../api/proactive", () => ({ PROACTIVE_CHANGED: "arslan:proactive-changed", announceProactiveChange: vi.fn(),
  proactiveApi: { scan: vi.fn() } }));
vi.mock("../components/ScheduledTasksCard", () => ({
  default: ({ onOpenRun }: { onOpenRun?: (id: number) => void }) => <button onClick={() => onOpenRun?.(42)}>run 42</button>,
}));
vi.mock("../components/proactive/WatchesPanel", () => ({ default: () => null }));
vi.mock("../components/proactive/NotDoneList", () => ({ default: () => null }));

import ScheduledPage from "../components/scheduled/ScheduledPage";
import { OPEN_ACTIVITY_RUN_EVENT } from "../components/reply/ReplyFooter";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

const attention = { tasks: {}, changes: {}, changeRows: {}, any: false, reload: async () => {} };

describe("a scheduled run", () => {
  it("opens on Progress, picked in the inspector, instead of a drawer", () => {
    const opened: number[] = [];
    const listen = (e: Event) => opened.push((e as CustomEvent<number>).detail);
    window.addEventListener(OPEN_ACTIVITY_RUN_EVENT, listen);
    try {
      render(<ScheduledPage attention={attention} waitingTasks={[]} onOpenConversation={() => {}} />);
      fireEvent.click(screen.getByRole("button", { name: "run 42" }));
      expect(opened).toEqual([42]);
      expect(screen.queryByTestId("run-drawer")).toBeNull();
      expect(screen.queryByRole("dialog")).toBeNull();
    } finally {
      window.removeEventListener(OPEN_ACTIVITY_RUN_EVENT, listen);
    }
  });
});

describe("the drawer's file", () => {
  it("is gone, and nothing imports it", () => {
    const files = import.meta.glob("../components/**/*.tsx", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    expect(Object.keys(files).some((path) => path.endsWith("/RunDrawer.tsx"))).toBe(false);
    expect(Object.entries(files).filter(([, source]) => source.includes("RunDrawer")).map(([path]) => path)).toEqual([]);
  });
});
