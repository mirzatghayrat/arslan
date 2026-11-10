/**
 * ThreadRowMenu — the per-conversation "⋯" overflow menu in the sidebar.
 *
 * Coverage:
 *  1. Opening "⋯" reveals archive / delete. Distill is gone (C8-5, v0.1.63).
 *  2. Clicking Archive calls onArchive(threadId).
 *  3. Clicking Delete shows a confirmation; confirming calls onDelete(threadId);
 *     canceling does not.
 *
 * i18n is mocked to echo keys so assertions are locale-independent.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import ThreadRowMenu from "../components/ThreadRowMenu";
import { ConfirmHost } from "../components/kit";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

function setup(overrides: Partial<React.ComponentProps<typeof ThreadRowMenu>> = {}) {
  const props = {
    threadId: "t1",
    onArchive: vi.fn(),
    onDelete: vi.fn(),
    ...overrides,
  };
  render(<ThreadRowMenu {...props} />);
  return props;
}

describe("ThreadRowMenu", () => {
  it("opening ⋯ reveals archive / delete, and no Distill", () => {
    setup();
    // closed initially
    expect(screen.queryByText("sidebar.archive")).toBeNull();
    fireEvent.click(screen.getByLabelText("sidebar.thread_menu"));
    expect(screen.getByText("sidebar.archive")).toBeTruthy();
    expect(screen.getByText("sidebar.delete")).toBeTruthy();
    // Manual distill was removed with its route (C8-5): the menu no longer offers it.
    expect(screen.queryByText("sidebar.distill")).toBeNull();
  });

  it("clicking Archive calls onArchive(threadId)", () => {
    const { onArchive } = setup();
    fireEvent.click(screen.getByLabelText("sidebar.thread_menu"));
    fireEvent.click(screen.getByText("sidebar.archive"));
    expect(onArchive).toHaveBeenCalledWith("t1");
  });

  it("Delete requires a confirmation before calling onDelete", async () => {
    const { onDelete } = setup();
    render(<ConfirmHost />);
    fireEvent.click(screen.getByLabelText("sidebar.thread_menu"));
    fireEvent.click(screen.getByText("sidebar.delete"));
    // 0.1.55: the kit's confirm sheet; onDelete not yet fired.
    expect(await screen.findByText("confirm.conversationBody")).toBeTruthy();
    expect(onDelete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("confirm-cancel"));
    await waitFor(() => expect(screen.queryByTestId("confirm-sheet")).toBeNull());
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("confirming the delete dialog calls onDelete(threadId)", async () => {
    const { onDelete } = setup();
    render(<ConfirmHost />);
    fireEvent.click(screen.getByLabelText("sidebar.thread_menu"));
    fireEvent.click(screen.getByText("sidebar.delete"));
    fireEvent.click(await screen.findByTestId("confirm-action"));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith("t1"));
  });

  it("by keyboard: focus into the menu, arrows wrap, Home and End, Esc closes, focus back on ⋯", () => {
    setup({ onRename: vi.fn(), onPin: vi.fn() });
    const more = screen.getByLabelText("sidebar.thread_menu");
    fireEvent.click(more);
    const menu = screen.getByRole("menu");
    const items = screen.getAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual(["sidebar.rename", "sidebar.pin", "sidebar.archive", "sidebar.delete"]);
    expect(document.activeElement).toBe(items[0]);
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(items[1]);
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(document.activeElement).toBe(items[3]);                    // wraps back
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(items[0]);                    // wraps forward
    fireEvent.keyDown(menu, { key: "End" });
    expect(document.activeElement).toBe(items[3]);
    fireEvent.keyDown(menu, { key: "Home" });
    expect(document.activeElement).toBe(items[0]);
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(more);
  });

  it("focus goes back on ⋯ on every close: an item, ⋯ itself, a click outside", () => {
    const { onArchive } = setup({ onPin: vi.fn() });
    const more = screen.getByLabelText("sidebar.thread_menu");
    const reopen = () => { fireEvent.click(more); expect(document.activeElement?.getAttribute("role")).toBe("menuitem"); };
    reopen();
    fireEvent.click(screen.getByText("sidebar.archive"));
    expect(onArchive).toHaveBeenCalledWith("t1");
    expect(document.activeElement).toBe(more);
    reopen();
    fireEvent.click(more);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(more);
    reopen();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(more);
  });

  it("Move to project: focus goes to the project list, and back to the list on Back", () => {
    setup({ projects: [{ id: "p1", name: "Alpha" }], onMove: vi.fn() });
    fireEvent.click(screen.getByLabelText("sidebar.thread_menu"));
    fireEvent.click(screen.getByText("sidebar.moveToProject"));
    expect(document.activeElement?.textContent).toBe("sidebar.moveBack");
    fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByTestId("thread-move-to-p1"));
    fireEvent.click(screen.getByText("sidebar.moveBack"));
    expect(document.activeElement?.textContent).toBe("sidebar.moveToProject");
  });

  it("in the archived variant, Unarchive calls onUnarchive(threadId)", () => {
    const onUnarchive = vi.fn();
    setup({ archived: true, onUnarchive });
    fireEvent.click(screen.getByLabelText("sidebar.thread_menu"));
    fireEvent.click(screen.getByText("sidebar.unarchive"));
    expect(onUnarchive).toHaveBeenCalledWith("t1");
  });
});
