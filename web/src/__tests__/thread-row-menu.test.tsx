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

  it("in the archived variant, Unarchive calls onUnarchive(threadId)", () => {
    const onUnarchive = vi.fn();
    setup({ archived: true, onUnarchive });
    fireEvent.click(screen.getByLabelText("sidebar.thread_menu"));
    fireEvent.click(screen.getByText("sidebar.unarchive"));
    expect(onUnarchive).toHaveBeenCalledWith("t1");
  });
});
