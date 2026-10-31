/** v0.1.64 UNI1b (the user's option B, 2026-10-31): each run of characters in a skill's text that show nothing is
 *  a marker, always; the save card says how many, and the import panel shows a count per found skill. Never
 *  blocking. The web and the server pass the same cases (spec/unicode/hidden-characters.json). */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup, within } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import vectors from "../../../spec/unicode/hidden-characters.json";
import * as discovery from "../api/discovery";
import AskSlot from "../components/AskSlot";
import SkillImportPanel from "../components/SkillImportPanel";
import { Escaped, hiddenCount, hiddenLabel, hiddenRuns } from "../lib/outsideText";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

type Case = { name: string; text: string; count: number; runs: string[] };
const CASES = (vectors as { cases: Case[] }).cases;
const MOCK = CASES.find(c => c.name === "the mock's skill text")!;
const HIDDEN = /[\u00AD\u034F\u115F\u1160\u200B\u2060-\u2065\u2800\u3164\uFEFF\uFFA0]|\u{E0100}/u;

beforeEach(() => useArslanStore.setState(initialArslanState(), true));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });

describe("hidden characters, the shared cases", () => {
  it.each(CASES.map(c => [c.name, c] as const))("%s", (_, c) => {
    expect(hiddenRuns(c.text).map(run => hiddenLabel(run.cps))).toEqual(c.runs);
    expect(hiddenCount(c.text)).toBe(c.count);
  });
});

describe("markers on the web", () => {
  it("Escaped shows each run as one marker in its place and keeps the rest as written", () => {
    const { container } = render(<Escaped text={MOCK.text} block />);
    expect(within(container).getAllByTestId("hidden-marker").map(m => m.textContent)).toEqual(MOCK.runs);
    expect(container.textContent).not.toMatch(HIDDEN);
    expect(container.textContent).toContain("\u2764\uFE0F Persian stays as written: \u0645\u06CC\u200C\u062E\u0648\u0627\u0647\u0645");
    expect(container.textContent).toContain("report.U+200B\n");
  });

  it("a bidi control keeps its own marker next to a hidden run", () => {
    const { container } = render(<Escaped text={"a\u202Eb\u200Bc"} />);
    expect(within(container).getByTestId("escaped-control").textContent).toBe("U+202E");
    expect(within(container).getByTestId("hidden-marker").textContent).toBe("U+200B");
    expect(container.textContent).toBe("aU+202EbU+200Bc");
  });

  it("the save card says how many, and each run is a marker in its text", () => {
    render(<AskSlot send={() => {}} />);
    frame({ type: "propose_capability", call_id: "cap-9", kind: "authored", key: "weekly-report", name: "Weekly report",
      description: "A one-page report", body: MOCK.text, why: "", outside: false });
    const body = screen.getByTestId("skill-save-body");
    expect(within(body).getAllByTestId("hidden-marker")).toHaveLength(MOCK.runs.length);
    expect(screen.getByTestId("skill-save-hidden").textContent).toContain('discover.save_hidden:{"count":32}');
    expect(screen.getByTestId("skill-save-allow")).toBeEnabled();               // shown, never blocking
  });

  it("the save card shows no notice for ordinary text", () => {
    render(<AskSlot send={() => {}} />);
    frame({ type: "propose_capability", call_id: "cap-9", kind: "authored", key: "plain", name: "Plain",
      description: "x", body: "## Trigger\nOrdinary text \u2764\uFE0F, \u0645\u06CC\u200C\u062E\u0648\u0627\u0647\u0645.\n", why: "",
      outside: false });
    expect(screen.queryByTestId("skill-save-hidden")).toBeNull();
    expect(screen.queryAllByTestId("hidden-marker")).toHaveLength(0);
  });

  it("the import panel shows a count and the runs for a found skill, and still offers it", async () => {
    vi.spyOn(discovery, "scanSkills").mockResolvedValue({
      repo: { full_name: "o/r", html_url: "https://github.com/o/r", license: "MIT", stars: 1 }, license_ok: true,
      license_note: null, skills: [
        { path: "a/SKILL.md", name: "Weekly report", description: "d", scripts: [], importable: true, reason: null,
          hidden: { count: 0, runs: [] } },
        { path: "b/SKILL.md", name: "Release notes", description: "d", scripts: [], importable: true, reason: null,
          hidden: { count: 23, runs: ["21 \u00D7 U+E0100\u2013E01EF", "2 \u00D7 U+200B"] } }],
    } as never);
    const { container } = render(<SkillImportPanel />);
    fireEvent.change(container.querySelector("input")!, { target: { value: "o/r" } });
    fireEvent.click(screen.getByText("capabilities.import.scan"));
    const badge = await screen.findByTestId("import-hidden");
    expect(screen.getAllByTestId("import-hidden")).toHaveLength(1);
    expect(badge.textContent).toBe('capabilities.import.hidden:{"count":23}');
    expect(screen.getByTestId("import-hidden-runs").textContent).toBe(
      'capabilities.import.hiddenRuns:{"runs":"21 \u00D7 U+E0100\u2013E01EF, 2 \u00D7 U+200B"}');
    expect(screen.getAllByText("capabilities.import.import").every(b => !(b.closest("button") as HTMLButtonElement).disabled))
      .toBe(true);
  });
});
