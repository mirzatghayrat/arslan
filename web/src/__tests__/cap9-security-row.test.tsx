// CAP9 (the install-card board the user OK'd, 2026-11-02): one row says what OSV.dev knows of the locked packages,
// the package itself first; "not checked" never reads as "none known"; a known vulnerability in the package itself
// makes "Don't install" the safe answer, and installing a red, deliberate click. Real strings (en).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "../i18n";
import CapabilityProposeCard from "../components/capabilities/CapabilityProposeCard";
import { osvLink } from "../components/capabilities/SecurityRow";
import type { Advisory, CapabilityCard, Vulns } from "../api/client.types";

afterEach(cleanup);

const CARD: CapabilityCard = {
  kind: "mcp", name: "notes-mcp", summary: "Reads and writes your notes", source_url: null, repo: null, version: "1.2.0",
  license: { spdx: "MIT", read_from: "LICENSE" }, stars: null, pushed_days: null, runtime: "uv", runtime_download: null,
  remote_host: null, network: false, folders: [], keys: [], why: "", retry: "",
};
const adv = (id: string, severity: Advisory["severity"], over: Partial<Advisory> = {}): Advisory =>
  ({ id, ids: [id], severity, summary: null, fixed: [], ...over });
const checked = (over: Partial<Extract<Vulns, { state: "checked" }>> = {}): Vulns =>
  ({ state: "checked", source: "OSV.dev", packages: 12, complete: true, count: 0, highest: null, own: [], deps: [], ...over });

function show(vulns?: Vulns, extra: Partial<CapabilityCard> = {}) {
  const onConfirm = vi.fn(), onCancel = vi.fn();
  render(<CapabilityProposeCard card={{ ...CARD, ...extra, vulns }} callId="c1" onConfirm={onConfirm} onCancel={onCancel} />);
  return { onConfirm, onCancel, row: () => screen.getByTestId("capability-card-security") };
}

describe("the security row", () => {
  it("none known, with what was asked", () => {
    const { row } = show(checked());
    expect(row()).toHaveTextContent("No known vulnerabilities in the 12 packages in the lock.");
    expect(row()).toHaveTextContent("Asked OSV.dev about the 12 public packages in the lock, by name and version only.");
    expect(screen.queryByTestId("vuln-toggle")).toBeNull();
  });

  it("a vulnerability in the package itself leads, its list open, each id linked to osv.dev", () => {
    const { row } = show(checked({ count: 1, highest: "HIGH", own: [adv("GHSA-aaaa-bbbb-cccc", "HIGH",
      { summary: "notes-mcp reads outside its folder", fixed: ["1.2.1"] })] }));
    expect(screen.getByTestId("vuln-summary")).toHaveTextContent("Known vulnerabilities in notes-mcp itself: 1. Highest: High.");
    const list = screen.getByTestId("vuln-list");
    expect(list).toBeVisible();
    expect(list).toHaveTextContent("notes-mcp reads outside its folder");
    expect(list).toHaveTextContent("fixed in 1.2.1");
    expect(within(list).getByRole("link")).toHaveAttribute("href", "https://osv.dev/vulnerability/GHSA-aaaa-bbbb-cccc");
    fireEvent.click(screen.getByTestId("vuln-toggle"));
    expect(screen.getByTestId("vuln-list")).not.toBeVisible();
    expect(row()).toHaveTextContent("Show the list");
  });

  it("only in its dependencies: said so, each dependency with its advisories (and its alias)", () => {
    show(checked({ count: 3, highest: "MODERATE", deps: [
      { name: "event-stream", alias: "innocent-name", version: "3.3.6", more: 1,
        advisories: [adv("GHSA-mh6f-8j2x-4483", "MODERATE"), adv("GHSA-xxxx-yyyy-zzzz", "LOW")] }] }));
    expect(screen.getByTestId("vuln-summary")).toHaveTextContent(
      "Known vulnerabilities only in its dependencies, not in notes-mcp itself: 3. Highest: Moderate.");
    const dep = screen.getByTestId("vuln-dep");
    expect(dep).toHaveTextContent("event-stream 3.3.6 (innocent-name)");
    expect(dep).toHaveTextContent("no fix yet");
    expect(dep).toHaveTextContent("and 1 more");
  });

  it("an incomplete answer says there may be more", () => {
    show(checked({ count: 1, highest: "LOW", complete: false, deps: [
      { name: "x", alias: null, version: "1", more: 0, advisories: [adv("GHSA-1111-2222-3333", "LOW")] }] }));
    expect(screen.getByTestId("vuln-incomplete")).toHaveTextContent("there may be more");
  });

  it.each([
    [{ state: "not_checked", why: "osv_did_not_answer" } as Vulns, "Not checked: OSV.dev didn't answer. This is not “none known”."],
    [{ state: "not_checked", why: "empty_lock" } as Vulns, "Not checked: the lock lists no packages."],
  ])("not checked is never none known (%#)", (vulns, text) => {
    const { row } = show(vulns);
    expect(screen.getByTestId("vuln-not-checked")).toHaveTextContent(text);
    expect(row()).toHaveTextContent("The lock, the scan and the sandbox still apply.");
    expect(row()).not.toHaveTextContent("No known vulnerabilities");
  });

  it.each([["remote", "it runs on its own server"], ["bundle", "a bundle names no packages OSV.dev knows"]])(
    "skipped: %s says why", (why, text) => {
      expect(show({ state: "skipped", why }).row()).toHaveTextContent(text);
    });

  it("a skill's card says skills aren't checked", () => {
    expect(show(undefined, { kind: "skill", runtime: "skill" }).row()).toHaveTextContent(
      "Skills aren't checked for known vulnerabilities");
  });

  it("an advisory id never becomes a link by itself", () => {
    expect(osvLink("javascript:alert(1)")).toBe("https://osv.dev/vulnerability/javascript%3Aalert(1)");
    expect(osvLink("RHSA-2023:1234")).toBe("https://osv.dev/vulnerability/RHSA-2023%3A1234");
  });
});

describe("the buttons, when the package itself has a known vulnerability (question 5, as the board draws it)", () => {
  const own = () => checked({ count: 1, highest: "CRITICAL", own: [adv("GHSA-aaaa-bbbb-cccc", "CRITICAL")] });

  it("'Don't install' is the safe answer and 'Install anyway' a red click", () => {
    const { onConfirm, onCancel } = show(own());
    expect(screen.getByTestId("capability-card-decline")).toHaveTextContent("Don't install");
    const install = screen.getByTestId("capability-card-allow");
    expect(install).toHaveTextContent("Install anyway");
    expect(install.className).toMatch(/destructive|danger/);
    fireEvent.click(screen.getByTestId("capability-card-decline"));
    expect(onCancel).toHaveBeenCalledWith("c1");
    fireEvent.click(install);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("no ⌘⏎ installs it", () => {
    const { onConfirm } = show(own());
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Enter", metaKey: true });
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("a vulnerability only in a dependency keeps the usual buttons", () => {
    show(checked({ count: 1, highest: "HIGH", deps: [
      { name: "x", alias: null, version: "1", more: 0, advisories: [adv("GHSA-1111-2222-3333", "HIGH")] }] }));
    expect(screen.getByTestId("capability-card-allow")).toHaveTextContent("Add and retry");
    expect(screen.getByTestId("capability-card-decline")).toHaveTextContent("Not now");
  });
});
