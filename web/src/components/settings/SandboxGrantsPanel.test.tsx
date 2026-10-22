import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const request = vi.fn();
vi.mock("../../api/client", () => ({ request: (...a: unknown[]) => request(...a) }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

import SandboxGrantsPanel from "./SandboxGrantsPanel";

describe("SandboxGrantsPanel (S4a)", () => {
  beforeEach(() => request.mockReset());

  it("lists each conversation whose commands may run outside the sandbox and takes one back", async () => {
    request.mockResolvedValueOnce([
      { id: 7, conversation_id: "c1", title: "tidy my Downloads" },
      { id: 9, conversation_id: "c2", title: "" },
    ]);
    render(<SandboxGrantsPanel />);
    expect(await screen.findByText("tidy my Downloads")).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith("/permissions/grants?kind=outside");
    expect(screen.getByText("settings.sandboxGrantsUntitled")).toBeInTheDocument();
    request.mockResolvedValueOnce({ ok: true });
    fireEvent.click(screen.getByTestId("sandbox-grant-take-back-7"));
    await waitFor(() => expect(screen.queryByText("tidy my Downloads")).toBeNull());
    expect(request).toHaveBeenLastCalledWith("/permissions/grants/7", { method: "DELETE" });
    expect(screen.getByTestId("sandbox-grant-take-back-9")).toBeInTheDocument();
  });

  it("says how one is added when there are none", async () => {
    request.mockResolvedValueOnce([]);
    render(<SandboxGrantsPanel />);
    expect(await screen.findByText("settings.sandboxGrantsEmpty")).toBeInTheDocument();
  });
});
