// CAP9 (the install-card board the user OK'd, 2026-11-02): one row says what OSV.dev knows of the locked packages,
// the package itself first; "not checked" never reads as "none known"; a known vulnerability in the package itself
// makes "Don't install" the safe answer, and installing a red, deliberate click. Real strings (en).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "../i18n";
import CapabilityProposeCard from "../components/capabilities/CapabilityProposeCard";
import { AskCard } from "../components/kit/AskCard";
import { osvLink } from "../components/capabilities/SecurityRow";
import type { Advisory, CapabilityCard, Vulns } from "../api/client.types";

afterEach(cleanup);

const CARD: CapabilityCard = {
  kind: "mcp", name: "notes-mcp", summary: "Reads and writes your notes", source_url: null, repo: null, version: "1.2.0",
  license: { spdx: "MIT", read_from: "LICENSE" }, stars: null, pushed_days: null, runtime: "uv", runtime_download: null,
  remote_host: null, network: false, folders: [], keys: [], why: "", retry: "",
};
const adv = (id: string, severity: Advisory["severity"], over: Partial<Advisory> = {}): Advisory =>
  ({ id, ids: [id], severity, summary: null, loaded: true, fixed: [], ...over });
const checked = (over: Partial<Extract<Vulns, { state: "checked" }>> = {}): Vulns =>
  ({ state: "checked", source: "OSV.dev", packages: 12, asked: 12, complete: true, count: 0, highest: null,
     own_highest: null, deps_highest: null, own: [], own_more: 0, deps: [], deps_more: 0, ...over });
const FSI = String.fromCharCode(0x2068), PDI = String.fromCharCode(0x2069);
const NAME = `${FSI}notes-mcp${PDI}`;                  // the card's name is isolated in a sentence (UNI1a)

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
    const { row } = show(checked({ count: 1, highest: "HIGH", own_highest: "HIGH", own: [adv("GHSA-aaaa-bbbb-cccc", "HIGH",
      { summary: "notes-mcp reads outside its folder", fixed: ["1.2.1"] })] }));
    expect(screen.getByTestId("vuln-summary")).toHaveTextContent(`Known vulnerabilities in ${NAME} itself: 1. Highest: High.`);
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
    show(checked({ count: 3, highest: "MODERATE", deps_highest: "MODERATE", deps: [
      { name: "event-stream", alias: "innocent-name", version: "3.3.6", more: 1,
        advisories: [adv("GHSA-mh6f-8j2x-4483", "MODERATE"), adv("GHSA-xxxx-yyyy-zzzz", "LOW")] }] }));
    expect(screen.getByTestId("vuln-summary")).toHaveTextContent(
      `Known vulnerabilities only in its dependencies, not in ${NAME} itself: 3. Highest: Moderate.`);
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
  const own = () => checked({ count: 1, highest: "CRITICAL", own_highest: "CRITICAL",
    own: [adv("GHSA-aaaa-bbbb-cccc", "CRITICAL")] });

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
    show(checked({ count: 1, highest: "HIGH", deps_highest: "HIGH", deps: [
      { name: "x", alias: null, version: "1", more: 0, advisories: [adv("GHSA-1111-2222-3333", "HIGH")] }] }));
    expect(screen.getByTestId("capability-card-allow")).toHaveTextContent("Add and retry");
    expect(screen.getByTestId("capability-card-decline")).toHaveTextContent("Not now");
  });
});

describe("#661 max review", () => {
  it("the package's own count and worst are its own, with the dependencies' said apart", () => {
    show(checked({ count: 5, highest: "CRITICAL", own_highest: "LOW", deps_highest: "CRITICAL", own_more: 1,
      own: [adv("GHSA-aaaa-aaaa-aaaa", "LOW"), adv("GHSA-bbbb-bbbb-bbbb", "LOW")],
      deps: [{ name: "x", alias: null, version: "1", more: 0,
        advisories: [adv("GHSA-cccc-cccc-cccc", "CRITICAL"), adv("GHSA-dddd-dddd-dddd", "LOW")] }] }));
    expect(screen.getByTestId("vuln-summary")).toHaveTextContent(`Known vulnerabilities in ${NAME} itself: 3. Highest: Low.`);
    expect(screen.getByTestId("vuln-also-deps")).toHaveTextContent("Also in its dependencies: 2. Highest: Critical.");
    expect(screen.getByTestId("vuln-list")).toHaveTextContent("and 1 more");
  });

  it("dependencies left off the list are counted", () => {
    show(checked({ count: 4, highest: "LOW", deps_highest: "LOW", deps_more: 3, deps: [
      { name: "x", alias: null, version: "1", more: 0, advisories: [adv("GHSA-1111-2222-3333", "LOW")] }] }));
    expect(screen.getByTestId("vuln-more-deps")).toHaveTextContent("and 3 more dependencies with known vulnerabilities");
    expect(screen.queryByTestId("vuln-also-deps")).toBeNull();
  });

  it("an advisory whose record did not load says so, never 'no fix yet'", () => {
    show(checked({ count: 1, highest: "UNKNOWN", own_highest: "UNKNOWN", complete: false,
      own: [adv("GHSA-aaaa-bbbb-cccc", "UNKNOWN", { loaded: false })] }));
    const list = screen.getByTestId("vuln-list");
    expect(list).toHaveTextContent("details not loaded");
    expect(list).not.toHaveTextContent("no fix yet");
  });

  it("a lock asked about in part says how much, and none known only of what was asked", () => {
    show(checked({ packages: 1500, asked: 1000, complete: false }));
    expect(screen.getByTestId("capability-card-allow")).toHaveTextContent("Add and retry");
    expect(screen.getByTestId("vuln-summary")).toHaveTextContent("No known vulnerabilities in the 1000 packages asked about.");
    expect(screen.getByTestId("vuln-summary")).not.toHaveTextContent("1500");
    expect(screen.getByTestId("vuln-asked")).toHaveTextContent(
      "Asked OSV.dev about 1000 of the 1500 public packages in the lock (the package itself first)");
  });

  it("no lock says there is none, never that OSV.dev didn't answer", () => {
    const { row } = show({ state: "skipped", why: "no_lock" });
    expect(row()).toHaveTextContent("Not checked: there is no lock to look up.");
    expect(row()).not.toHaveTextContent("didn't answer");
  });

  it("a name with direction controls cannot turn the sentence around", () => {
    show(checked({ count: 1, highest: "HIGH", own_highest: "HIGH", own: [adv("GHSA-aaaa-bbbb-cccc", "HIGH")] }),
      { name: "notes" + String.fromCharCode(0x202e) + "-mcp" });
    expect(screen.getByTestId("vuln-summary").textContent).toContain(`in ${FSI}notes-mcp${PDI} itself`);
  });
});

describe("question 5's buttons on a card the package itself is vulnerable in", () => {
  const own = () => checked({ count: 1, highest: "HIGH", own_highest: "HIGH", own: [adv("GHSA-aaaa-bbbb-cccc", "HIGH")] });

  it("'Don't install' leads and has focus; 'Install anyway' draws no ⌘⏎ hint", () => {
    show(own());
    const decline = screen.getByTestId("capability-card-decline"), install = screen.getByTestId("capability-card-allow");
    expect(document.activeElement).toBe(decline);
    expect(decline.className).toContain("bg-foreground");                  // the primary tone (⓪Plan's probe)
    expect(decline.className).not.toContain("bg-fill");
    expect(decline.style.flex).toMatch(/^1\.4/);
    expect(install.style.flex).toMatch(/^1( |$)/);
    expect(install).not.toHaveTextContent("⌘⏎");
    expect(decline).toHaveTextContent("esc");
  });

  it("esc still answers No", () => {
    const { onCancel } = show(own());
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledWith("c1");
  });

  it("it stays the top surface: ⌘⏎ never answers a card behind it", () => {
    const behind = vi.fn(), behindNo = vi.fn(), onConfirm = vi.fn(), onCancel = vi.fn();
    render(<>
      <AskCard who="Arslan" title="Run the plan" onAllow={behind} onDecline={behindNo} testId="behind" />
      <CapabilityProposeCard card={{ ...CARD, vulns: own() }} callId="c1" onConfirm={onConfirm} onCancel={onCancel} />
    </>);
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(behind).not.toHaveBeenCalled();
    expect(behindNo).not.toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalledWith("c1");
  });

  it("while the user types elsewhere, focus stays where it is", () => {
    const box = document.createElement("textarea");
    document.body.appendChild(box);
    box.focus();
    show(own());
    expect(document.activeElement).toBe(box);
    box.remove();
  });

  it("a card with no known vulnerability in the package keeps ⌘⏎ and its usual focus", () => {
    const { onConfirm } = show(checked());
    expect(document.activeElement).not.toBe(screen.getByTestId("capability-card-decline"));
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});

describe("⓪Plan's #661 probes at 0a5f0e20, each now asserting the fixed behaviour", () => {
  it("an ordinary install card mounted over a plan card still takes ⌘⏎ itself", () => {
    const other = vi.fn(), onConfirm = vi.fn();
    render(<>
      <AskCard who="plan" title="Take the new plan?" onAllow={other} onDecline={vi.fn()} testId="plan" />
      <CapabilityProposeCard card={{ ...CARD }} callId="c1" onConfirm={onConfirm} onCancel={vi.fn()} />
    </>);
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(other).not.toHaveBeenCalled();
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("the name in the row's sentence is isolated, as the title's is", () => {
    const name = "\u0645\u0644\u0627\u062d\u0638\u0627\u062a";        // Arabic letters, no control characters
    show(checked({ count: 1, highest: "HIGH", own_highest: "HIGH", own: [adv("GHSA-aaaa-bbbb-cccc", "HIGH")] }), { name });
    expect(screen.getByTestId("vuln-summary").textContent).toContain(`${FSI}${name}${PDI}`);
    expect(screen.getByRole("heading").textContent).toContain(`${FSI}${name}${PDI}`);
  });

  it("the package's own count is its total, not the advisories listed", () => {
    const own10 = Array.from({ length: 10 }, (_, i) => adv(`GHSA-aaaa-bbbb-cc${i.toString().padStart(2, "0")}`, "HIGH"));
    show(checked({ packages: 3, count: 25, highest: "HIGH", own_highest: "HIGH", own: own10, own_more: 15 }));
    expect(screen.getByTestId("vuln-summary")).toHaveTextContent(`Known vulnerabilities in ${NAME} itself: 25. Highest: High.`);
    expect(screen.getByTestId("vuln-list")).toHaveTextContent("and 15 more");
  });
});
