/** 0.1.57 P4: "Arslan 找到的", a candidate's dossier, "Arslan 加的" and its dossier, the quiet count. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import FoundRail from "../components/capabilities/FoundRail";
import CandidateDossier, { START_PROJECT_EVENT } from "../components/capabilities/CandidateDossier";
import AddedCapabilities from "../components/capabilities/AddedCapabilities";
import { ConfirmHost } from "../components/kit";
import { capabilitiesApi, type CapabilityCandidate, type CapabilityFind, type CapabilitySource } from "../api/capabilities";
import { companionApi, type Project } from "../api/companion";

const CAND: CapabilityCandidate = {
  id: "registry:x@1.1.2", kind: "mcp", name: "excel-mcp-server", summary: "Reads and writes .xlsx", source: "registry",
  source_url: "https://github.com/haris-musa/excel-mcp-server", repo: "haris-musa/excel-mcp-server", version: "1.1.2",
  runtime: "uv", package: { registry_type: "pypi", identifier: "excel-mcp-server", version: "1.1.2" }, remote: null,
  not_here: null, needs: { keys: [{ name: "EXCEL_TOKEN", secret: true, required: true, description: "" }], network: null },
  license: { spdx: "MIT", read_from: "github:LICENSE", verdict: "usable" }, stars: 4216, pushed_days: 10, checked_at: null, path: null,
};
const FIND: CapabilityFind = { id: "f1", need: "read formulas", why: "declined", conversation_id: "c1", project_id: null,
  level_id: null, candidate: CAND, created_at: "" };
const SOURCE: CapabilitySource = {
  id: "s1", kind: "mcp", name: "excel-mcp-server", candidate_id: CAND.id, source_url: CAND.source_url, repo: CAND.repo,
  version: "1.1.2", commit_sha: null, artifact_sha256: null, lock_sha256: "823d3b6ba54d10e57c532c8c0bbb50fe",
  license: { spdx: "MIT", read_from: "LICENSE" }, stars: 4216, pushed_days: 10, checked_at: null, runtime: "uv",
  needs: {}, grants: { folders: ["/Users/x/Downloads"], network: false }, scan: { level: "clean", findings: [] },
  test: { ok: true, tools: ["read_range", "write_range"] }, files: null, state: "installed", error: null,
  mcp_server_id: 3, skill_key: null, installed_at: null,
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Arslan found", () => {
  it("says why it looked, what it found and the license; Not interested dismisses it", async () => {
    const finds = vi.spyOn(capabilitiesApi, "finds").mockResolvedValueOnce([FIND]).mockResolvedValueOnce([]);
    const dismiss = vi.spyOn(capabilitiesApi, "dismissFind").mockResolvedValue({ ok: true });
    render(<FoundRail />);
    expect(await screen.findByTestId("find-f1")).toHaveTextContent('discover.rail_why_declined:{"need":"read formulas"}');
    expect(screen.getByTestId("find-f1")).toHaveTextContent("MIT");
    fireEvent.click(screen.getByTestId("find-dismiss-f1"));
    await waitFor(() => expect(dismiss).toHaveBeenCalledWith("f1"));
    await waitFor(() => expect(finds).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("discover.rail_none")).toBeInTheDocument();
  });

  it("Look opens the candidate's dossier", async () => {
    vi.spyOn(capabilitiesApi, "finds").mockResolvedValue([FIND]);
    vi.spyOn(capabilitiesApi, "checkCandidate").mockResolvedValue({ candidate: CAND, installable: true, why_not: null });
    vi.spyOn(companionApi, "projects").mockResolvedValue([]);
    render(<FoundRail />);
    fireEvent.click(await screen.findByTestId("find-open-f1"));
    expect(await screen.findByTestId("candidate-dossier")).toBeInTheDocument();
  });
});

describe("a candidate's dossier", () => {
  const PROJECT = { id: "p1", name: "Budget" } as unknown as Project;

  it("checks the license at the source, then adds it with the folder and the required key", async () => {
    vi.spyOn(capabilitiesApi, "checkCandidate").mockResolvedValue({ candidate: CAND, installable: true, why_not: null });
    vi.spyOn(companionApi, "projects").mockResolvedValue([]);
    const install = vi.spyOn(capabilitiesApi, "install").mockResolvedValue({ state: "on", source_id: "s1", tools: ["a", "b"] });
    render(<CandidateDossier candidate={CAND} onClose={() => {}} />);
    expect(await screen.findByTestId("dossier-install")).toBeInTheDocument();
    expect(screen.getByTestId("dossier-license")).toHaveTextContent("MIT · github:LICENSE");
    expect(screen.getByTestId("dossier-add")).toBeDisabled();                       // the key is required
    fireEvent.change(screen.getByTestId("dossier-key-EXCEL_TOKEN"), { target: { value: "k" } });
    fireEvent.change(screen.getByTestId("dossier-folder"), { target: { value: " ~/Downloads " } });
    fireEvent.click(screen.getByTestId("dossier-add"));
    await waitFor(() => expect(install).toHaveBeenCalledWith(CAND.id, ["~/Downloads"], { EXCEL_TOKEN: "k" }));
    expect(await screen.findByTestId("dossier-result")).toHaveTextContent('discover.result_on:{"name":"excel-mcp-server","count":2}');
  });

  it("says why it cannot be added, and offers no add button", async () => {
    vi.spyOn(capabilitiesApi, "checkCandidate").mockResolvedValue({
      candidate: { ...CAND, license: { spdx: null, read_from: "LICENSE.txt", verdict: "reference_only" } },
      installable: false, why_not: "license_not_usable" });
    vi.spyOn(companionApi, "projects").mockResolvedValue([]);
    render(<CandidateDossier candidate={CAND} onClose={() => {}} />);
    expect(await screen.findByTestId("dossier-why-not")).toHaveTextContent("discover.why_license_not_usable");
    expect(screen.queryByTestId("dossier-install")).toBeNull();
  });

  it("goes into a project as material, or as a dependency through a typed conversation", async () => {
    vi.spyOn(capabilitiesApi, "checkCandidate").mockResolvedValue({ candidate: CAND, installable: true, why_not: null });
    vi.spyOn(companionApi, "projects").mockResolvedValue([PROJECT]);
    const material = vi.spyOn(capabilitiesApi, "asMaterial").mockResolvedValue({ collection_id: 4, chunks: 3 });
    const onClose = vi.fn();
    const events: CustomEvent[] = [];
    const listen = (e: Event) => events.push(e as CustomEvent);
    window.addEventListener(START_PROJECT_EVENT, listen);
    render(<CandidateDossier candidate={CAND} onClose={onClose} />);
    fireEvent.change(await screen.findByTestId("dossier-project"), { target: { value: "p1" } });
    fireEvent.click(screen.getByTestId("dossier-as-material"));
    await waitFor(() => expect(material).toHaveBeenCalledWith("p1", CAND.id));
    expect(await screen.findByTestId("dossier-project-note")).toHaveTextContent("discover.dossier_materialDone");
    fireEvent.click(screen.getByTestId("dossier-as-dependency"));
    window.removeEventListener(START_PROJECT_EVENT, listen);
    expect(events[0].detail.projectId).toBe("p1");
    expect(events[0].detail.prefill).toContain("discover.dossier_dependencyPrefill");
    expect(onClose).toHaveBeenCalled();
  });
});

describe("added by Arslan", () => {
  it("lists what was installed; its dossier shows the pin, the scan and the test", async () => {
    vi.spyOn(capabilitiesApi, "sources").mockResolvedValue([SOURCE]);
    render(<AddedCapabilities />);
    expect(await screen.findByTestId("added-s1")).toHaveTextContent("discover.added_on");
    fireEvent.click(screen.getByTestId("added-open-s1"));
    expect(screen.getByTestId("source-version")).toHaveTextContent('discover.source_lock:{"sha":"823d3b6ba54d10e5"}');
    expect(screen.getByTestId("source-scan")).toHaveTextContent("discover.scan_clean");
    expect(screen.getByTestId("source-test")).toHaveTextContent('discover.source_testOk:{"count":2}');
  });

  it("folders, an update (what changed first, then on click), and removal (asked first)", async () => {
    vi.spyOn(capabilitiesApi, "sources").mockResolvedValue([SOURCE]);
    const folders = vi.spyOn(capabilitiesApi, "setFolders").mockResolvedValue({ ...SOURCE, grants: { folders: ["/a", "/b"] } });
    vi.spyOn(capabilitiesApi, "checkUpdate").mockResolvedValue({ current: "1.1.2", latest: "1.2.0", newer: true,
      compare_url: "https://github.com/x/compare/v1.1.2...v1.2.0" });
    const update = vi.spyOn(capabilitiesApi, "update").mockResolvedValue({ state: "on", source_id: "s2" });
    const remove = vi.spyOn(capabilitiesApi, "remove").mockResolvedValue({ ok: true });
    render(<><AddedCapabilities /><ConfirmHost /></>);
    fireEvent.click(await screen.findByTestId("added-open-s1"));
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
    vi.spyOn(capabilitiesApi, "sources").mockResolvedValue([SOURCE]);
    vi.spyOn(capabilitiesApi, "checkUpdate").mockResolvedValue({ current: "1.1.2", latest: "1.1.2", newer: false });
    const remove = vi.spyOn(capabilitiesApi, "remove").mockResolvedValue({ ok: true });
    render(<><AddedCapabilities /><ConfirmHost /></>);
    fireEvent.click(await screen.findByTestId("added-open-s1"));
    fireEvent.click(screen.getByTestId("source-check-update"));
    expect(await screen.findByTestId("source-update")).toHaveTextContent("discover.source_current");
    expect(screen.queryByTestId("source-apply-update")).toBeNull();
    fireEvent.click(screen.getByTestId("source-remove"));
    fireEvent.click(await screen.findByTestId("confirm-cancel"));
    await new Promise((r) => setTimeout(r, 20));
    expect(remove).not.toHaveBeenCalled();
  });

  it("shows nothing when Arslan added nothing", async () => {
    vi.spyOn(capabilitiesApi, "sources").mockResolvedValue([]);
    render(<AddedCapabilities />);
    await waitFor(() => expect(capabilitiesApi.sources).toHaveBeenCalled());
    expect(screen.queryByTestId("added-capabilities")).toBeNull();
  });
});
