/**
 * ASK1-b (v0.1.64): migration 0097 leaves `scheduled_commands_note = "pending"` on an existing install. The Scheduled
 * page shows the note once and writes "seen" at once, so it never shows again; nobody else ever sees it.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const { updateSettings } = vi.hoisted(() => ({ updateSettings: vi.fn() }));
vi.mock("../api/client", async (orig) => ({ ...(await orig<object>()), api: { updateSettings } }));

import ScheduledCommandsNote from "../components/scheduled/ScheduledCommandsNote";
import { useSettingsStore } from "../stores/settingsStore";
import type { AppSettings } from "../api/client.types";

function withFlag(flag: string | undefined) {
  const settings = {} as AppSettings;
  if (flag !== undefined) settings.scheduled_commands_note = flag;
  act(() => useSettingsStore.getState().setSettings(settings));
}

describe("ScheduledCommandsNote", () => {
  beforeEach(() => {
    updateSettings.mockReset();
    updateSettings.mockResolvedValue({});
    useSettingsStore.setState({ settings: null });
  });

  it("a told user sees it once, and it is marked seen at once", async () => {
    withFlag("pending");
    render(<ScheduledCommandsNote />);
    const note = screen.getByTestId("scheduled-commands-note");
    expect(note.textContent).toContain("scheduledPage.commandsNoteTitle");
    expect(note.textContent).toContain("scheduledPage.commandsNoteBody");
    expect(updateSettings).toHaveBeenCalledTimes(1);
    expect(updateSettings).toHaveBeenCalledWith({ scheduled_commands_note: "seen" });
    await waitFor(() => expect(useSettingsStore.getState().settings?.scheduled_commands_note).toBe("seen"));
    fireEvent.click(screen.getByTestId("scheduled-commands-note-ok"));
    expect(screen.queryByTestId("scheduled-commands-note")).toBeNull();
  });

  it.each([["seen"], [""], [undefined]])("nobody else sees it (flag %s)", (flag) => {
    withFlag(flag);
    render(<ScheduledCommandsNote />);
    expect(screen.queryByTestId("scheduled-commands-note")).toBeNull();
    expect(updateSettings).not.toHaveBeenCalled();
  });

  it("a stale reload that says pending again after it was marked seen does not show it twice", async () => {
    withFlag("pending");
    render(<ScheduledCommandsNote />);
    await waitFor(() => expect(useSettingsStore.getState().settings?.scheduled_commands_note).toBe("seen"));
    fireEvent.click(screen.getByTestId("scheduled-commands-note-ok"));
    withFlag("pending");
    expect(screen.queryByTestId("scheduled-commands-note")).toBeNull();
    expect(updateSettings).toHaveBeenCalledTimes(1);
  });
});
