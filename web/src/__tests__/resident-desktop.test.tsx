import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

import DesktopSection from "../components/settings/DesktopSection";
import { conversationToOpen } from "../lib/openConversation";
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

  it("is a no-op in a plain browser", () => {
    const cb = vi.fn();
    const unsubscribe = subscribeOpenConversation(cb);
    expect(typeof unsubscribe).toBe("function");
    unsubscribe();
    expect(cb).not.toHaveBeenCalled();
  });
});
