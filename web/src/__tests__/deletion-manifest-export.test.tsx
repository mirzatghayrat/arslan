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
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(request).toHaveBeenCalledWith("/memory/deletion-manifest", { cache: "no-store" });
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce();
    expect(document.querySelector("a[download]")).toBeNull();
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:synthetic-export"), { timeout: 2000 });
  });

  it("does not download errors or expose backend diagnostics", async () => {
    vi.mocked(request).mockRejectedValue(new Error("private diagnostic"));
    render(<DeletionManifestExport />);
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByRole("alert")).toHaveTextContent("companion.deletionManifestFailure");
    expect(screen.queryByText("private diagnostic")).toBeNull();
    expect(create).not.toHaveBeenCalled();
  });

  it("deduplicates pending clicks and drops results after departure", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(request).mockReturnValue(new Promise(done => { resolve = done; }));
    const view = render(<DeletionManifestExport />);
    fireEvent.click(screen.getByRole("button"));
    fireEvent.click(screen.getByRole("button"));
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
    }
  });
});
