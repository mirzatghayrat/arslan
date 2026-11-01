/** v0.1.64 UNI1a (docs/plans/0164/CAPX-followups.md): every place that shows outside skill or connection text
 *  goes through lib/outsideText. A skill's text keeps its format characters (ZWNJ, ZWJ, VS16, LRM/RLM); a bidi
 *  override or isolate control shows as a marker, never reorders what is read: the card shows what is stored. */
import { readFileSync } from "node:fs";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup, within } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import * as client from "../api/client";
import * as discovery from "../api/discovery";
import AskSlot from "../components/AskSlot";
import CapabilitySheet from "../components/CapabilitySheet";
import SkillImportPanel from "../components/SkillImportPanel";
import InboxRefused from "../components/proactive/InboxRefused";
import { Escaped, isolate } from "../lib/outsideText";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

const RLO = "\u202E", PDF = "\u202C", RLI = "\u2067", PDI = "\u2069";
const KEEP = "می\u200Cخواهم 👨\u200D👩\u200D👧 ❤\uFE0F a\u200Fb\u200Ec";      // kept as written
const REORDERING = /[\u202A-\u202E\u2066-\u2069]/;
const MIXED = `pay ${RLO}gnp.exe${PDF} and ${RLI}x${PDI} ${KEEP}`;

beforeEach(() => useArslanStore.setState(initialArslanState(), true));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });

function shownEscaped(el: HTMLElement) {
  expect(el.textContent).not.toMatch(REORDERING);
  expect(within(el).getAllByTestId("escaped-control").map(m => m.textContent)).toEqual(["U+202E", "U+202C", "U+2067", "U+2069"]);
  expect(el.textContent).toContain(KEEP);
}

describe("outside text on the web", () => {
  it("Escaped shows each reordering control as a marker and keeps every other character", () => {
    const { container } = render(<Escaped text={MIXED} />);
    shownEscaped(container);
    expect(container.textContent).toBe(`pay U+202Egnp.exeU+202C and U+2067xU+2069 ${KEEP}`);
    expect(isolate(`a${RLO}b`)).toBe("\u2068ab\u2069");
  });

  it("the save card shows the skill's text as stored, a bidi control as a marker", () => {
    render(<AskSlot send={() => {}} />);
    frame({ type: "propose_capability", call_id: "cap-9", kind: "authored", key: "weekly-report", name: "Weekly report",
      description: MIXED, body: `## Trigger\n${MIXED}\n`, why: "", outside: false });
    shownEscaped(screen.getByTestId("skill-save-body"));
    shownEscaped(within(screen.getByTestId("skill-save-rows")).getAllByText((_, el) => el?.tagName === "BDI")[0] as HTMLElement);
  });

  it("the install card shows what it does, a bidi control as a marker", () => {
    render(<AskSlot send={() => {}} />);
    frame({ type: "propose_capability", call_id: "cap-1", kind: "mcp", name: "excel", summary: MIXED, source_url: null,
      repo: null, version: null, license: { spdx: "MIT", read_from: null }, stars: null, pushed_days: null, runtime: "uv",
      runtime_download: null, remote_host: null, network: false, folders: [], keys: [], why: "", retry: "" });
    shownEscaped(screen.getByTestId("capability-card-rows"));
  });

  it("the import panel shows each found skill's name and description, a bidi control as a marker", async () => {
    vi.spyOn(discovery, "scanSkills").mockResolvedValue({
      repo: { full_name: "o/r", html_url: "https://github.com/o/r", license: "MIT", stars: 1 }, license_ok: true,
      license_note: null, skills: [{ path: "s/SKILL.md", name: MIXED, description: MIXED, scripts: [], importable: true, reason: null }],
    });
    const { container } = render(<SkillImportPanel />);
    fireEvent.change(container.querySelector("input")!, { target: { value: "o/r" } });
    fireEvent.click(screen.getByText("capabilities.import.scan"));
    const found = await screen.findAllByText((_, el) => el?.tagName === "BDI" && el.textContent?.startsWith("pay") === true);
    expect(found).toHaveLength(2);
    found.forEach(el => shownEscaped(el as HTMLElement));
  });

  it("the details sheet shows a skill's name and what it does, a bidi control as a marker (#526 review)", () => {
    const row = { key: "skill:weekly", section: "skills", origin: "installed", deletable: false, source_id: null,
      state: "on", switch: "skill", tools: [], reason: null, fix: null, name: MIXED, detail: MIXED } as never;
    render(<CapabilitySheet row={row} name={MIXED} what={MIXED} used="" onClose={() => {}} onDelete={() => {}}
      onChanged={() => {}} />);
    shownEscaped(screen.getByTestId("cap-sheet-what"));
    shownEscaped(screen.getByTestId("cap-sheet").querySelector("bdi")!.parentElement as HTMLElement);
  });

  it("an away entry shows what was attempted as stored and the rule's name isolated in Arslan's sentence (#602 review)", async () => {
    // What was attempted is a command, or one of Arslan's sentences around a UI element's or a file's name; the rule's label is an app's name.
    vi.spyOn(client, "request").mockImplementation((async (path: string) => path.startsWith("/approvals/refused") ? [{
      id: 7, created_at: "2026-11-01T09:00:00Z", first_at: "2026-11-01T09:00:00Z", count: 1, conversation_id: "c", kind: "app",
      target: "app:x", detail: MIXED, always_ok: true, always: [{ kind: "app", target: "x", label: MIXED }], unattended: false,
    }] : {}) as never);
    render(<InboxRefused conversationId="c" />);
    const what = await screen.findByTestId("inbox-refused-what");
    shownEscaped(what);
    expect(what.parentElement!.getAttribute("title")).toBe(isolate(MIXED));
    const rule = screen.getByTestId("inbox-refused-rule");
    expect(rule.getAttribute("title")).toBe(isolate(MIXED));
    expect(rule.textContent).toBe(`inbox.alwaysStores:${JSON.stringify({ what: isolate(MIXED) })}`);
  });

  it("every component that shows outside skill or connection text uses lib/outsideText", () => {
    // A new one fails here until it is listed, with a test above. Names come from the server already cleaned
    // (untrusted.clean_name at every write, models.py; migration 0082 for those stored before; the tools list),
    // so this list is for text shown as stored (a skill's text) and names inside Arslan's own sentences.
    for (const file of ["CapabilitySwitches.tsx", "CapabilitySheet.tsx", "SkillImportPanel.tsx",
      "capabilities/SkillSaveCard.tsx", "capabilities/CapabilityProposeCard.tsx", "proactive/InboxRefused.tsx"]) {
      expect(readFileSync(`src/components/${file}`, "utf8"), file).toMatch(/from "(\.\.\/)+lib\/outsideText"|from '\.\.\/lib\/outsideText'/);
    }
  });
});
