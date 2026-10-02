import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

import DesktopSection from "../components/settings/DesktopSection";
import { conversationToOpen, INBOX_TARGET, notificationTarget } from "../lib/openConversation";
import { subscribeOpenConversation } from "../lib/shell";
import { FIELD_HOMES } from "../components/settings/sectionRegistry";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Desktop settings (0.1.41 resident mode)", () => {
  it("shows both switches with the values it is given and reports changes", () => {
    const keepAwake = vi.fn();
    const notify = vi.fn();
    render(<DesktopSection keepAwakeEnabled notificationsEnabled={false}
      onKeepAwakeChange={keepAwake} onNotificationsChange={notify} />);
    const awake = screen.getByTestId("settings-keep-awake-toggle") as HTMLInputElement;
    const notes = screen.getByTestId("settings-desktop-notifications-toggle") as HTMLInputElement;
    expect(awake.checked).toBe(true);
    expect(notes.checked).toBe(false);
    fireEvent.click(awake);
    fireEvent.click(notes);
    expect(keepAwake).toHaveBeenCalledWith(false);
    expect(notify).toHaveBeenCalledWith(true);
    expect(screen.getByText("settings.desktopLede")).toBeInTheDocument();
  });

  it("has the notch switch, on unless turned off, and reports changes (0.1.51)", () => {
    const island = vi.fn();
    const { rerender } = render(<DesktopSection keepAwakeEnabled notificationsEnabled onIslandChange={island} />);
    const toggle = screen.getByTestId("settings-island-toggle") as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    fireEvent.click(toggle);
    expect(island).toHaveBeenCalledWith(false);
    rerender(<DesktopSection keepAwakeEnabled notificationsEnabled islandEnabled={false} onIslandChange={island} />);
    expect((screen.getByTestId("settings-island-toggle") as HTMLInputElement).checked).toBe(false);
    expect(FIELD_HOMES["desktop.island"]).toBe("desktop");
  });

  it("lives in its own section, not under the spend-only Automation copy", () => {
    expect(FIELD_HOMES["desktop.keep_awake"]).toBe("desktop");
    expect(FIELD_HOMES["desktop.notifications"]).toBe("desktop");
  });
});

describe("opening a conversation from a notification", () => {
  const threads = [{ id: "main" }, { id: "t2", archived: true }, { id: "t3" }];

  it("opens only a conversation the user already has and has not archived", () => {
    expect(conversationToOpen("t3", threads)).toBe("t3");
    expect(conversationToOpen("t2", threads)).toBeNull();
    expect(conversationToOpen("scheduled-9", threads)).toBeNull();
    expect(conversationToOpen("", threads)).toBeNull();
  });

  it("a proactive notice opens the Inbox; anything else only a known conversation (0.1.47)", () => {
    // "@inbox" is what resident.rs puts in a proactive notification's id.
    expect(INBOX_TARGET).toBe("@inbox");
    expect(notificationTarget("@inbox", threads)).toEqual({ kind: "inbox" });
    expect(notificationTarget("t3", threads)).toEqual({ kind: "conversation", id: "t3" });
    expect(notificationTarget("t2", threads)).toBeNull();
    expect(notificationTarget("@inboxx", threads)).toBeNull();
  });

  it("is a no-op in a plain browser", () => {
    const cb = vi.fn();
    const unsubscribe = subscribeOpenConversation(cb);
    expect(typeof unsubscribe).toBe("function");
    unsubscribe();
    expect(cb).not.toHaveBeenCalled();
  });
});
