/** 0.1.57 P1: the Discover results — by what you want done, license at the source, how it runs. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import DiscoverResults, { runLine } from "../components/capabilities/DiscoverResults";
import type { CapabilityCandidate, CapabilitySearch } from "../api/capabilities";

const t = (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key);
const cand = (over: Partial<CapabilityCandidate>): CapabilityCandidate => ({
  id: "registry:x@1", kind: "mcp", name: "excel-mcp-server", summary: "Reads and writes .xlsx", source: "registry",
  source_url: "https://github.com/haris-musa/excel-mcp-server", repo: "haris-musa/excel-mcp-server", version: "1.1.2",
  runtime: "uv", package: { registry_type: "pypi", identifier: "excel-mcp-server", version: "1.1.2" }, remote: null,
  not_here: null, needs: { keys: [], network: null }, license: { spdx: "MIT", read_from: "github:LICENSE", verdict: "usable" },
  stars: 4212, pushed_days: 10, checked_at: null, path: null, ...over,
});
const RESULT: CapabilitySearch = { words: ["excel"], notes: [], candidates: [
  cand({}),
  cand({ id: "library:xlsx", kind: "skill", name: "xlsx", runtime: "skill", repo: "anthropics/skills", source: "library",
    license: { spdx: null, read_from: "skills/xlsx/LICENSE.txt", verdict: "reference_only" }, stars: null, pushed_days: null }),
  cand({ id: "github:openpyxl", kind: "project", name: "openpyxl", runtime: null, package: null, source: "github" }),
] };

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("how each candidate would run, said in one line", () => {
  it("covers every case, and the license comes first", () => {
    expect(runLine(t, cand({}))).toBe("discover.run_uv");
    expect(runLine(t, cand({ runtime: "node" }))).toBe("discover.run_node");
    expect(runLine(t, cand({ runtime: "remote", remote: { type: "streamable-http", url: "https://mcp.example.com/x" } })))
      .toBe('discover.run_remote:{"host":"mcp.example.com"}');
    expect(runLine(t, cand({ kind: "skill", runtime: "skill" }))).toBe("discover.run_skill");
    expect(runLine(t, cand({ kind: "project", runtime: null }))).toBe("discover.run_project");
    expect(runLine(t, cand({ runtime: null, not_here: "needs_dotnet" }))).toBe("discover.nh_needs_dotnet");
    expect(runLine(t, cand({ license: { spdx: "GPL-3.0", read_from: null, verdict: "reference_only" } }))).toBe("discover.ref_only");
    expect(runLine(t, cand({ license: { spdx: null, read_from: null, verdict: "unknown" } }))).toBe("discover.unknown_only");
    // A project with no license found can still be read about; it is not installed either way.
    expect(runLine(t, cand({ kind: "project", runtime: null, license: { spdx: null, read_from: null, verdict: "unknown" } })))
      .toBe("discover.run_project");
  });
});

describe("the results", () => {
  it("filters by kind with counts and shows license, activity and the run line", () => {
    render(<DiscoverResults result={RESULT} onLook={() => {}} onSave={() => {}} />);
    expect(screen.getByTestId("discover-filter-all")).toHaveTextContent("3");
    expect(screen.getByTestId("discover-filter-skill")).toHaveTextContent("1");
    expect(screen.getByTestId("cand-license-registry:x@1")).toHaveTextContent('discover.lic_usable:{"spdx":"MIT"}');
    expect(screen.getByTestId("cand-license-library:xlsx")).toHaveTextContent("discover.lic_reference");
    expect(screen.getByTestId("cand-run-library:xlsx")).toHaveTextContent("discover.ref_only");
    expect(screen.getByTestId("cand-registry:x@1")).toHaveTextContent('discover.pushed:{"count":10}');
    fireEvent.click(screen.getByTestId("discover-filter-skill"));
    expect(screen.queryByTestId("cand-registry:x@1")).toBeNull();
    expect(screen.getByTestId("cand-library:xlsx")).toBeInTheDocument();
  });

  it("Look and Save hand the candidate back; a source that did not answer says so", () => {
    const onLook = vi.fn(), onSave = vi.fn();
    render(<DiscoverResults result={{ ...RESULT, notes: ["registry_unavailable"] }} onLook={onLook} onSave={onSave} />);
    fireEvent.click(screen.getByTestId("cand-look-registry:x@1"));
    fireEvent.click(screen.getByTestId("cand-save-github:openpyxl"));
    expect(onLook.mock.calls[0][0].id).toBe("registry:x@1");
    expect(onSave.mock.calls[0][0].id).toBe("github:openpyxl");
    expect(screen.getByTestId("discover-note-registry_unavailable")).toBeInTheDocument();
  });

  it("no words: says so instead of an empty list; required keys are named", () => {
    const { unmount } = render(<DiscoverResults result={{ words: [], notes: ["no_keywords"], candidates: [] }} onLook={() => {}} onSave={() => {}} />);
    expect(screen.getByTestId("discover-note-no_keywords")).toBeInTheDocument();
    expect(screen.queryByText("discover.none")).toBeNull();
    unmount();
    render(<DiscoverResults result={{ words: ["x"], notes: [], candidates: [cand({ needs: { network: true, keys: [
      { name: "API_KEY", secret: true, required: true, description: "" }, { name: "OPTIONAL", secret: false, required: false, description: "" }] } })] }}
      onLook={() => {}} onSave={() => {}} />);
    expect(screen.getByText('discover.needsKeys:{"keys":"API_KEY"}')).toBeInTheDocument();
  });
});
