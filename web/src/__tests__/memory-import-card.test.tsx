/** v0.1.64 CAP8b: the import card. Each line with its tick, what it says the same as, what was left out and why, and an
 *  answer that names exactly the lines left ticked. */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act, cleanup, within } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o ? `${key}:${JSON.stringify(o)}` : key) }),
}));

import AskSlot from "../components/AskSlot";
import { ANSWER_GUARD_MS } from "../components/kit";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

beforeEach(() => useArslanStore.setState(initialArslanState(), true));
afterEach(() => { cleanup(); vi.useRealTimers(); });
const settle = () => act(() => { vi.advanceTimersByTime(ANSWER_GUARD_MS); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });

const CARD = {
  type: "propose_capability", call_id: "m-1", kind: "memory_import", name: "memories", why: "they pasted it", lines: 41,
  too_many: 0, keys: [], folders: [],
  entries: [
    { id: "e0", text: "Works mostly in Python and Swift", ticked: true, same_as: null },
    { id: "e1", text: "Prefers the result first, then the reasons", ticked: false, same_as: "Likes short replies" },
    { id: "e2", text: "Here is my list", ticked: false, same_as: null },
    { id: "e3", text: "Has a cat called Miso", ticked: true, same_as: null },
  ],
  left_out: [
    { text: "Was fixing a bug in login.py on Tuesday", reason: "one_off" },
    { text: "Running the site on localhost:3000 this week", reason: "one_off" },
    { text: "Probably male, going by the name", reason: "gender" },
    { text: "Likes short replies", reason: "stored" },
    { text: null, reason: "credential" },
  ],
};
const INSTALL = {
  type: "propose_capability", call_id: "cap-1", kind: "mcp", name: "excel-mcp-server", summary: "Reads and writes .xlsx",
  source_url: null, repo: null, version: null, license: { spdx: "MIT", read_from: null }, stars: null, pushed_days: null,
  runtime: "uv", runtime_download: null, remote_host: null, network: false, folders: [], keys: [], why: "", retry: "",
};
const tick = (id: string) => screen.getByTestId(`memory-import-tick-${id}`) as HTMLInputElement;
const save = () => screen.getByTestId("memory-import-allow") as HTMLButtonElement;

describe("the import card", () => {
  it("says where the lines came from, and draws the mock's rows, its note and its footer", () => {
    render(<AskSlot send={() => {}} />);
    frame(CARD);
    const card = screen.getByTestId("memory-import-card");
    expect(card).toHaveTextContent("discover.import_who");
    expect(card).toHaveTextContent("discover.import_title");
    expect(screen.getByTestId("memory-import-from")).toHaveTextContent('discover.import_fromText:{"count":41}');
    expect(card).toHaveTextContent("discover.import_noteText");
    expect(card).toHaveTextContent("discover.import_footer");
    expect(screen.getByTestId("memory-import-decline")).toHaveTextContent("discover.import_decline");
    expect(screen.queryByTestId("ask-said")).toBeNull();                       // the mock has no words of the model's
    expect(screen.queryByTestId("capability-card-license")).toBeNull();        // none of the install card's rows
  });

  it("starts with the server's ticks and counts them on Save", () => {
    render(<AskSlot send={() => {}} />);
    frame(CARD);
    expect(CARD.entries.map(e => tick(e.id).checked)).toEqual([true, false, false, true]);
    expect(save()).toHaveTextContent('discover.import_allow:{"count":2}');
    fireEvent.click(tick("e2"));
    expect(save()).toHaveTextContent('discover.import_allow:{"count":3}');
    fireEvent.click(tick("e0"));
    expect(save()).toHaveTextContent('discover.import_allow:{"count":2}');
  });

  it("names the stored memory beside a line that says the same, and gives a plain unticked line no reason", () => {
    render(<AskSlot send={() => {}} />);
    frame(CARD);
    expect(screen.getByTestId("memory-import-same-e1")).toHaveTextContent(
      'discover.import_same:{"stored":"⁨Likes short replies⁩"}');
    expect(screen.queryByTestId("memory-import-same-e0")).toBeNull();
    expect(screen.queryByTestId("memory-import-same-e2")).toBeNull();
  });

  it("disables Save at no ticks, for the click and for the keyboard, and esc still says no", () => {
    vi.useFakeTimers();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(CARD);
    settle();
    fireEvent.click(tick("e0"));
    fireEvent.click(tick("e3"));
    expect(save().disabled).toBe(true);
    expect(save()).toHaveTextContent('discover.import_allow:{"count":0}');
    fireEvent.click(save());
    fireEvent.keyDown(window, { key: "Enter", metaKey: true });
    expect(send).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(send).toHaveBeenCalledWith({ type: "cancel_capability", call_id: "m-1" });
  });

  it("answers with exactly the ids left ticked, in the card's order, and never the text", () => {
    vi.useFakeTimers();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(CARD);
    settle();
    fireEvent.click(tick("e2"));
    fireEvent.click(tick("e1"));
    fireEvent.click(tick("e3"));
    fireEvent.click(save());
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith({ type: "confirm_capability", call_id: "m-1", kept: ["e0", "e1", "e2"] });
    expect(useArslanStore.getState().pendingCapabilities).toEqual([]);
  });

  it("answers the server's ticks when none changed", () => {
    vi.useFakeTimers();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(CARD);
    settle();
    fireEvent.click(save());
    expect(send).toHaveBeenCalledWith({ type: "confirm_capability", call_id: "m-1", kept: ["e0", "e3"] });
  });

  it("Not now says no with nothing kept", () => {
    vi.useFakeTimers();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(CARD);
    settle();
    fireEvent.click(screen.getByTestId("memory-import-decline"));
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith({ type: "cancel_capability", call_id: "m-1" });
    expect(useArslanStore.getState().pendingCapabilities).toEqual([]);
  });

  it("keeps a line unticked after paging to another card and back", () => {
    vi.useFakeTimers();
    const send = vi.fn();
    render(<AskSlot send={send} />);
    frame(CARD);
    frame(INSTALL);
    settle();
    fireEvent.click(tick("e0"));
    const nav = (where: string) => screen.getByTestId("ask-queue").querySelector<HTMLElement>(`[data-nav="${where}"]`)!;
    fireEvent.click(nav("next"));
    expect(screen.getByTestId("capability-card")).toBeInTheDocument();
    settle();
    fireEvent.click(nav("prev"));
    settle();
    expect(tick("e0").checked).toBe(false);
    fireEvent.click(save());
    expect(send).toHaveBeenCalledWith({ type: "confirm_capability", call_id: "m-1", kept: ["e3"] });
  });

  it("shows what was left out as a count until opened, each with its reason, and a key's line never", () => {
    render(<AskSlot send={() => {}} />);
    frame(CARD);
    const left = screen.getByTestId("memory-import-left");
    expect(left).toHaveTextContent('"count":5');
    expect(left).toHaveTextContent('discover.import_part_one_off:{\\"count\\":2}');
    expect(left).toHaveTextContent('discover.import_part_gender:{\\"count\\":1}');
    expect(left).toHaveTextContent('discover.import_part_stored:{\\"count\\":1}');
    expect(left).toHaveTextContent('discover.import_part_credential:{\\"count\\":1}');
    expect(left).not.toHaveTextContent("Was fixing a bug");
    expect(screen.queryByTestId("memory-import-left-list")).toBeNull();
    const toggle = screen.getByTestId("memory-import-left-toggle");
    expect(toggle).toHaveTextContent("discover.import_show");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveTextContent("discover.import_hide");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByTestId("memory-import-left-list");
    expect(list).toHaveTextContent("Was fixing a bug in login.py on Tuesday");
    expect(within(list).getAllByText("discover.import_why_one_off")).toHaveLength(2);
    expect(list).toHaveTextContent("discover.import_why_gender");
    expect(list).toHaveTextContent("discover.import_why_stored");
    expect(list).toHaveTextContent("discover.import_keyLine");
    expect(list).toHaveTextContent("discover.import_why_credential");
    fireEvent.click(toggle);
    expect(screen.queryByTestId("memory-import-left-list")).toBeNull();
  });

  it("draws no Left out row when nothing was left out", () => {
    render(<AskSlot send={() => {}} />);
    frame({ ...CARD, left_out: [] });
    expect(screen.queryByTestId("memory-import-left")).toBeNull();
    expect(screen.queryByTestId("memory-import-too-many")).toBeNull();
  });

  it("says what too_many means", () => {
    render(<AskSlot send={() => {}} />);
    frame({ ...CARD, left_out: [], too_many: 7 });
    expect(screen.getByTestId("memory-import-too-many")).toHaveTextContent('discover.import_tooMany:{"count":7}');
    expect(screen.queryByTestId("memory-import-left-toggle")).toBeNull();     // nothing to open: those lines aren't sent
  });

  it("shows a pasted line as plain text, with a bidi control and a hidden run marked (stored equals shown)", () => {
    render(<AskSlot send={() => {}} />);
    frame({ ...CARD, left_out: [], entries: [
      { id: "e0", text: "<img src=x onerror=\"alert(1)\"> **not bold** [a link](https://evil.example)", ticked: true, same_as: null },
      { id: "e1", text: "safe‮txet​​more", ticked: true, same_as: null },
    ] });
    const card = screen.getByTestId("memory-import-card");
    expect(card.querySelector("img, a, strong")).toBeNull();
    const line = screen.getByTestId("memory-import-line-e1");
    expect(line.textContent).toContain("U+202E");
    expect(line.textContent).toContain("U+200B");
    expect(screen.getByTestId("memory-import-hidden")).toHaveTextContent('discover.save_hidden:{"count":2}');
  });

  it("draws no hidden notice for ordinary text, Persian's joiner included", () => {
    render(<AskSlot send={() => {}} />);
    frame({ ...CARD, left_out: [], entries: [
      { id: "e0", text: "می‌خواهم", ticked: true, same_as: null },
    ] });
    expect(screen.queryByTestId("memory-import-hidden")).toBeNull();
  });

  it("leaves the other two cards on this frame alone", () => {
    render(<AskSlot send={() => {}} />);
    frame(INSTALL);
    expect(screen.getByTestId("capability-card")).toBeInTheDocument();
    expect(screen.queryByTestId("memory-import-card")).toBeNull();
  });
});
