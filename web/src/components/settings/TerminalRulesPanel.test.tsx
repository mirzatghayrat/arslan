import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const request = vi.fn();
vi.mock("../../api/client", () => ({ request: (...a: unknown[]) => request(...a) }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

import TerminalRulesPanel from "./TerminalRulesPanel";

describe("TerminalRulesPanel", () => {
  beforeEach(() => request.mockReset());

  it("lists every remembered rule in the card's words and forgets one on click", async () => {
    request.mockResolvedValueOnce({ rules: [
      { rule: "hermes:recursive delete", description: "recursive delete" },
      { rule: "install", description: "installs software" },
    ] });
    render(<TerminalRulesPanel />);
    expect(await screen.findByText("recursive delete")).toBeInTheDocument();
    request.mockResolvedValueOnce({ rules: [{ rule: "install", description: "installs software" }] });
    fireEvent.click(screen.getByTestId("terminal-rule-forget-hermes:recursive delete"));
    await waitFor(() => expect(screen.queryByText("recursive delete")).toBeNull());
    // The rule name has a space and a colon: it must travel encoded, as a query parameter.
    expect(request).toHaveBeenLastCalledWith(
      "/settings/terminal-rules?rule=hermes%3Arecursive%20delete", { method: "DELETE" });
    expect(screen.getByText("installs software")).toBeInTheDocument();
  });

  it("says how to add one when there are none", async () => {
    request.mockResolvedValueOnce({ rules: [] });
    render(<TerminalRulesPanel />);
    expect(await screen.findByText("settings.terminalRulesEmpty")).toBeInTheDocument();
  });
});
