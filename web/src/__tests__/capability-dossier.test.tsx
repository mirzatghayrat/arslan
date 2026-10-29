/** 0.1.57 P4: the dossier of what was installed from a card (v0.1.64 CAP3a: opened from its row's details sheet;
 *  the separate "Arslan 加的" list went into the one list). */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import { SourceDossier } from "../components/capabilities/AddedCapabilities";
import { ConfirmHost } from "../components/kit";
import { capabilitiesApi, type CapabilitySource } from "../api/capabilities";

const SOURCE: CapabilitySource = {
  id: "s1", kind: "mcp", name: "excel-mcp-server", candidate_id: "registry:x@1.1.2",
  source_url: "https://github.com/haris-musa/excel-mcp-server", repo: "haris-musa/excel-mcp-server",
  version: "1.1.2", commit_sha: null, artifact_sha256: null, lock_sha256: "823d3b6ba54d10e57c532c8c0bbb50fe",
  license: { spdx: "MIT", read_from: "LICENSE" }, stars: 4216, pushed_days: 10, checked_at: null, runtime: "uv",
  needs: {}, grants: { folders: ["/Users/x/Downloads"], network: false }, scan: { level: "clean", findings: [] },
  test: { ok: true, tools: ["read_range", "write_range"] }, files: null, state: "installed", error: null,
  mcp_server_id: 3, skill_key: null, installed_at: null,
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the dossier of what was installed", () => {
  it("the dossier shows the pin, the scan and the test", async () => {
    render(<SourceDossier source={SOURCE} onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(screen.getByTestId("source-version")).toHaveTextContent('discover.source_lock:{"sha":"823d3b6ba54d10e5"}');
    expect(screen.getByTestId("source-scan")).toHaveTextContent("discover.scan_clean");
    expect(screen.getByTestId("source-test")).toHaveTextContent('discover.source_testOk:{"count":2}');
  });

  it("folders, an update (what changed first, then on click), and removal (asked first)", async () => {
    const folders = vi.spyOn(capabilitiesApi, "setFolders").mockResolvedValue({ ...SOURCE, grants: { folders: ["/a", "/b"] } });
    vi.spyOn(capabilitiesApi, "checkUpdate").mockResolvedValue({ current: "1.1.2", latest: "1.2.0", newer: true,
      compare_url: "https://github.com/x/compare/v1.1.2...v1.2.0" });
    const update = vi.spyOn(capabilitiesApi, "update").mockResolvedValue({ state: "on", source_id: "s2" });
    const remove = vi.spyOn(capabilitiesApi, "remove").mockResolvedValue({ ok: true });
    render(<><SourceDossier source={SOURCE} onClose={vi.fn()} onChanged={vi.fn()} /><ConfirmHost /></>);
    fireEvent.change(screen.getByTestId("source-folders"), { target: { value: "/a\n\n /b " } });
    fireEvent.click(screen.getByTestId("source-folders-save"));
    await waitFor(() => expect(folders).toHaveBeenCalledWith("s1", ["/a", "/b"]));
    fireEvent.click(screen.getByTestId("source-check-update"));
    expect(await screen.findByTestId("source-update")).toHaveTextContent('discover.source_newer:{"current":"1.1.2","latest":"1.2.0"}');
    expect(update).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("source-apply-update"));
    await waitFor(() => expect(update).toHaveBeenCalledWith("s1"));
    fireEvent.click(screen.getByTestId("source-remove"));
    expect(remove).not.toHaveBeenCalled();                                      // asked first
    fireEvent.click(await screen.findByTestId("confirm-action"));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("s1"));
  });

  it("no update button when it is the newest; a declined remove removes nothing", async () => {
    vi.spyOn(capabilitiesApi, "checkUpdate").mockResolvedValue({ current: "1.1.2", latest: "1.1.2", newer: false });
    const remove = vi.spyOn(capabilitiesApi, "remove").mockResolvedValue({ ok: true });
    render(<><SourceDossier source={SOURCE} onClose={vi.fn()} onChanged={vi.fn()} /><ConfirmHost /></>);
    fireEvent.click(screen.getByTestId("source-check-update"));
    expect(await screen.findByTestId("source-update")).toHaveTextContent("discover.source_current");
    expect(screen.queryByTestId("source-apply-update")).toBeNull();
    fireEvent.click(screen.getByTestId("source-remove"));
    fireEvent.click(await screen.findByTestId("confirm-cancel"));
    await new Promise((r) => setTimeout(r, 20));
    expect(remove).not.toHaveBeenCalled();
  });
});
