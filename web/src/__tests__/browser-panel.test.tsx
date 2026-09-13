import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "../i18n";
import BrowserPanel from "../components/BrowserPanel";
import { browserApi } from "../api/browser";
import { api } from "../api/client";

vi.mock("../api/browser", () => ({ browserApi: { status: vi.fn(), setup: vi.fn(), start: vi.fn(), visit: vi.fn() } }));
vi.mock("../api/client", () => ({ api: { cancelRun: vi.fn(), downloadRunArtifact: vi.fn() } }));

beforeEach(() => {
  vi.resetAllMocks();
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  vi.mocked(browserApi.status).mockResolvedValue({ ready: true, reason: null, version: "0.0.80" });
  vi.mocked(browserApi.visit).mockResolvedValue({ run_id: 8, status: "recording", result: null, artifacts: [] });
  vi.mocked(api.cancelRun).mockResolvedValue({ ok: true });
});

describe("static browser preview", () => {
  it("downloads only after an explicit click", async () => {
    vi.mocked(browserApi.status).mockResolvedValue({ ready: false, reason: "setup_required", version: "0.0.80" });
    vi.mocked(browserApi.setup).mockResolvedValue({ ready: true, reason: null, version: "0.0.80" });
    render(<BrowserPanel open onClose={vi.fn()} />);
    await screen.findByText("The optional browser runtime is not installed.");
    expect(browserApi.setup).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
    fireEvent.click(screen.getByText("Download browser runtime"));
    await waitFor(() => expect(browserApi.setup).toHaveBeenCalledOnce());
    expect(screen.getByText(/Page scripts are disabled/)).toBeInTheDocument();
  });

  it("reuses a request key after a lost response and supports stop", async () => {
    vi.mocked(browserApi.start).mockRejectedValueOnce(new Error("lost response")).mockResolvedValueOnce({ run_id: 8 });
    render(<BrowserPanel open onClose={vi.fn()} />);
    const input = screen.getByLabelText("Public HTTPS address");
    await waitFor(() => expect(input).not.toBeDisabled());
    fireEvent.change(input, { target: { value: "https://example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByRole("button", { name: "Stop" });
    expect(vi.mocked(browserApi.start).mock.calls[0]).toEqual(vi.mocked(browserApi.start).mock.calls[1]);
    fireEvent.click(screen.getByText("Stop"));
    await waitFor(() => expect(api.cancelRun).toHaveBeenCalledWith(8));
  });
});
