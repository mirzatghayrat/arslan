// 0.1.45 hands: the confirmation card for browser / Mac actions.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ActionApprovalCard from "../components/ActionApprovalCard";
import { handsMessages } from "../locales/hands";
import { initialArslanState, useArslanStore } from "../stores/arslanStore";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string, o?: Record<string, string>) =>
  o ? `${k}:${Object.values(o).join("|")}` : k }) }));
afterEach(() => { cleanup(); useArslanStore.setState(initialArslanState(), true); });

describe("action approval card", () => {
  it("shows an AppleScript in full and answers with the buttons", () => {
    const onConfirm = vi.fn(), onCancel = vi.fn();
    render(<ActionApprovalCard kind="mac_script" target="AppleScript" detail={'tell application "Reminders" to count reminders'}
      onConfirm={onConfirm} onCancel={onCancel} />);
    expect(screen.getByTestId("action-script")).toHaveTextContent('tell application "Reminders" to count reminders');
    fireEvent.click(screen.getByTestId("action-allow"));
    fireEvent.click(screen.getByTestId("action-deny"));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("names the website for a browser action", () => {
    render(<ActionApprovalCard kind="browser_site" target="https://github.com" detail="click" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText("hands.title.browser_site:https://github.com")).toBeInTheDocument();
  });

  it("the store holds a job's action card and raises the spoken notice", () => {
    useArslanStore.getState().handleFrame({ type: "propose_action", call_id: "a1", kind: "mac_shortcut",
      target: "Log water", detail: "Run the Shortcut", background: true });
    expect(useArslanStore.getState().pendingAction).toMatchObject({ callId: "a1", kind: "mac_shortcut" });
    expect(useArslanStore.getState().jobNotice).toMatchObject({ kind: "needs_approval" });
  });

  it("has the same keys in all six languages", () => {
    const flat = (o: object, p = ""): string[] => Object.entries(o).flatMap(([k, v]) =>
      typeof v === "object" ? flat(v, `${p}${k}.`) : [`${p}${k}`]);
    const keys = flat(handsMessages.en).sort();
    for (const messages of Object.values(handsMessages)) expect(flat(messages).sort()).toEqual(keys);
  });
});
