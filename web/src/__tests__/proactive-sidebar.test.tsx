import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import Sidebar from "../components/Sidebar";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../components/companion/BackgroundJobs", () => ({ default: () => null }));
afterEach(cleanup);

const props = (over: Partial<React.ComponentProps<typeof Sidebar>> = {}): React.ComponentProps<typeof Sidebar> => ({
  threads: [], activeThreadId: "", onSelectThread: vi.fn(), onAddThread: vi.fn(), activeSection: "arslan", onChangeSection: vi.fn(),
  onDistillThread: vi.fn(), onArchiveThread: vi.fn(), onUnarchiveThread: vi.fn(), onDeleteThread: vi.fn(),
  backendStatus: "online", ...over,
});

describe("Inbox in the sidebar", () => {
  it("opens the inbox", () => {
    const p = props();
    render(<Sidebar {...p} />);
    fireEvent.click(document.getElementById("nav-btn-inbox-deck")!);
    expect(p.onChangeSection).toHaveBeenCalledWith("inbox");
  });

  it("shows no badge with nothing unread", () => {
    render(<Sidebar {...props({ inboxUnread: 0 })} />);
    expect(screen.queryByTestId("inbox-badge")).toBeNull();
  });

  it("counts unread, caps the number, and colours it when something needs a look", () => {
    const { rerender } = render(<Sidebar {...props({ inboxUnread: 3, inboxHigh: 0 })} />);
    expect(screen.getByTestId("inbox-badge").textContent).toBe("3");
    expect(screen.getByTestId("inbox-badge").className).toContain("bg-primary");
    rerender(<Sidebar {...props({ inboxUnread: 140, inboxHigh: 1 })} />);
    expect(screen.getByTestId("inbox-badge").textContent).toBe("99+");
    expect(screen.getByTestId("inbox-badge").className).toContain("bg-warning");
  });

  it("0.1.57: what Arslan found shows as a quiet count beside Capabilities, none when zero", () => {
    const { rerender } = render(<Sidebar {...props({ capabilityFinds: 0 })} />);
    expect(screen.queryByTestId("capabilities-badge")).toBeNull();
    rerender(<Sidebar {...props({ capabilityFinds: 3 })} />);
    expect(screen.getByTestId("capabilities-badge")).toHaveTextContent("3");
    expect(screen.getByTestId("capabilities-badge").className).not.toContain("bg-primary");   // quiet, not an alert
  });
});
