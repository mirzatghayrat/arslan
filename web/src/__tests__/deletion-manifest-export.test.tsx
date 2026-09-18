import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { request } from "../api/client";
import DeletionManifestExport from "../components/settings/DeletionManifestExport";
import { companionMessages } from "../locales/companion";

vi.mock("../api/client", () => ({ request: vi.fn() }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const create = vi.fn(() => "blob:synthetic-export");
const revoke = vi.fn();

describe("deletion manifest export", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("URL", { createObjectURL: create, revokeObjectURL: revoke });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("downloads only after an explicit click with no-store authentication helper", async () => {
    vi.mocked(request).mockResolvedValue({ format: 1, deletions: [] });
    render(<DeletionManifestExport />);
    expect(request).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "companion.exportDeletionManifest" }));
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(request).toHaveBeenCalledWith("/memory/deletion-manifest", { cache: "no-store" });
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce();
    expect(document.querySelector("a[download]")).toBeNull();
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:synthetic-export"), { timeout: 2000 });
  });

  it("does not download errors or expose backend diagnostics", async () => {
    vi.mocked(request).mockRejectedValue(new Error("private diagnostic"));
    render(<DeletionManifestExport />);
    fireEvent.click(screen.getByRole("button", { name: "companion.exportDeletionManifest" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("companion.deletionManifestFailure");
    expect(screen.queryByText("private diagnostic")).toBeNull();
    expect(create).not.toHaveBeenCalled();
  });

  it("deduplicates pending clicks and drops results after departure", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(request).mockReturnValue(new Promise(done => { resolve = done; }));
    const view = render(<DeletionManifestExport />);
    const button = screen.getByRole("button", { name: "companion.exportDeletionManifest" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(request).toHaveBeenCalledOnce();
    view.unmount(); resolve({ format: 1, deletions: [] });
    await Promise.resolve();
    expect(create).not.toHaveBeenCalled();
  });

  it("has explicit export, limitation and error copy in all six languages", () => {
    expect(Object.keys(companionMessages)).toHaveLength(6);
    for (const messages of Object.values(companionMessages)) {
      expect(messages.exportDeletionManifest.length).toBeGreaterThan(3);
      expect(messages.deletionManifestHint.length).toBeGreaterThan(30);
      expect(messages.deletionManifestFailure.length).toBeGreaterThan(10);
      expect(messages.checkDeletionRecord.length).toBeGreaterThan(3);
      expect(messages.deletionRecordCurrent.length).toBeGreaterThan(20);
      expect(messages.deletionRecordAhead.length).toBeGreaterThan(20);
      expect(messages.deletionRecordAttention.length).toBeGreaterThan(20);
    }
  });

  it.each([
    [{ status: "current", database_epoch: 2, saved_epoch: 2 }, "Current"],
    [{ status: "current", database_epoch: 2, saved_epoch: 1 }, "Attention"],
    [{ status: "current" }, "Attention"],
    [{ status: "ahead", database_epoch: 1, saved_epoch: 2 }, "Ahead"],
    [{ status: "missing" }, "Attention"],
    [{ status: "stale" }, "Attention"],
    [{ status: "unavailable" }, "Attention"],
  ])("checks local status without exporting or claiming restore completion: %j", async (result, suffix) => {
    vi.mocked(request).mockResolvedValue(result);
    render(<DeletionManifestExport />);
    expect(request).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "companion.checkDeletionRecord" }));
    expect(await screen.findByRole("status")).toHaveTextContent(`companion.deletionRecord${suffix}`);
    expect(request).toHaveBeenCalledWith("/memory/deletion-record-status", { cache: "no-store" });
    expect(create).not.toHaveBeenCalled();
  });

  it("reports status failures without exposing private diagnostics", async () => {
    vi.mocked(request).mockRejectedValue(new Error("private record path"));
    render(<DeletionManifestExport />);
    fireEvent.click(screen.getByRole("button", { name: "companion.checkDeletionRecord" }));
    expect(await screen.findByRole("status")).toHaveTextContent("companion.deletionRecordAttention");
    expect(screen.queryByText("private record path")).toBeNull();
  });

  it("deduplicates pending status checks and ignores a departed result", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(request).mockReturnValue(new Promise(done => { resolve = done; }));
    const view = render(<DeletionManifestExport />);
    const button = screen.getByRole("button", { name: "companion.checkDeletionRecord" });
    fireEvent.click(button); fireEvent.click(button);
    expect(request).toHaveBeenCalledOnce();
    view.unmount(); resolve({ status: "current", database_epoch: 1, saved_epoch: 1 });
    await Promise.resolve();
    expect(screen.queryByRole("status")).toBeNull();
    expect(create).not.toHaveBeenCalled();
  });
});
