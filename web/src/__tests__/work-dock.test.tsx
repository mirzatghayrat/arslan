import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import WorkDock from "../components/WorkDock";
import { DOCK_KEY, openArtifact, restoreDock, saveDock } from "../lib/workDock";
import { dockMessages } from "../locales/dock";
import type { StoredArtifact } from "../api/client.types";

vi.mock("../components/BrowserReader", () => ({ default: ({ conversationId }: { conversationId: string }) => <div>Reader: {conversationId}</div> }));
vi.mock("../components/BrowserPanel", () => ({ default: () => null }));
vi.mock("../components/ArtifactPreview", () => ({ default: ({ file }: { file: StoredArtifact }) => <div>File: {file.title}</div> }));
const file: StoredArtifact = { kind: "file", run_id: 42, filename: "report.txt", title: "Saved report", bytes: 10,
  sha256: "a".repeat(64), media_type: "text/plain", url: "https://evil.test/do-not-use?secret=token" };
beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("work dock", () => {
  it("supports tabs, keyboard focus, width and close while preserving metadata only", () => {
    render(<WorkDock open onOpen={() => {}} onClose={() => {}} conversationId="conversation" taskId="task" temporary={false} />);
    fireEvent.click(screen.getAllByText("dock.newBrowser")[0]);
    fireEvent.click(screen.getByLabelText("dock.newBrowser"));
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    fireEvent.keyDown(tabs[1], { key: "ArrowLeft" });
    expect(tabs[0]).toHaveFocus();
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    const width = Number(screen.getByRole("separator").getAttribute("aria-valuenow"));
    fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowLeft" });
    expect(Number(screen.getByRole("separator").getAttribute("aria-valuenow"))).toBe(width + 20);
    fireEvent.click(screen.getAllByLabelText("dock.closeTab")[0]);
    expect(screen.getAllByRole("tab")).toHaveLength(1);
    expect(restoreDock().tabs).toHaveLength(1);
  });
  it("opens verified-shaped file references without following an external URL", () => {
    const open = vi.fn();
    render(<WorkDock open onOpen={open} onClose={() => {}} conversationId="conversation" taskId={null} temporary={false} />);
    act(() => openArtifact(file));
    expect(open).toHaveBeenCalledOnce();
    expect(screen.getByText("File: Saved report")).toBeVisible();
    expect(localStorage.getItem(DOCK_KEY)).not.toContain("evil.test");
    expect(localStorage.getItem(DOCK_KEY)).not.toContain("secret");
  });
  it("never persists temporary tabs when switching back to a regular conversation", () => {
    saveDock([{ id: "temp", kind: "browser", conversationId: "private-conversation", taskId: null, temporary: true },
      { id: "regular", kind: "browser", conversationId: "ordinary", taskId: null, title: "private-page-title" }], 400, false);
    expect(localStorage.getItem(DOCK_KEY)).not.toContain("private");
    expect(restoreDock().tabs).toHaveLength(1);
  });
  it("does not accept a path or fabricated artifact shape from persisted state", () => {
    localStorage.setItem(DOCK_KEY, JSON.stringify({ tabs: [{ id: "bad", kind: "artifact", file: { ...file, filename: "../key" } }] }));
    expect(restoreDock().tabs).toEqual([]);
  });
  it("has matching nonempty copy and interpolation in all six languages", () => {
    const keys = Object.keys(dockMessages.en);
    for (const messages of Object.values(dockMessages)) {
      expect(Object.keys(messages).sort()).toEqual([...keys].sort());
      for (const key of keys as (keyof typeof messages)[]) {
        expect(messages[key].trim()).not.toBe("");
        expect(messages[key].match(/\{\{[^}]+\}\}/g) ?? []).toEqual(dockMessages.en[key].match(/\{\{[^}]+\}\}/g) ?? []);
      }
    }
  });
});
