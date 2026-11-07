/** L11-3b: a practice narrowed to one folder says so in Memory: on its row, under the current practices, and in the
 *  sheet that turns one on. Real strings, so the wording in each language is what is asserted. */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";
import i18n from "../i18n";
import MemoryList from "../components/companion/MemoryList";
import { ConfirmHost } from "../components/kit";
import { lessonsApi, type Lesson } from "../api/lessons";
import { companionApi } from "../api/companion";

const FOLDER = "~/Code/arslan";
const HINT_EN = "A practice you corrected twice in one folder applies only there. Correct it once in another folder and it applies everywhere again.";
const HINT_ZH = "在同一个文件夹里纠正过两次的做法，只在那个文件夹生效。到别的文件夹再纠正一次，就恢复成到哪都用。";

const lesson = (over: Partial<Lesson>): Lesson => ({ id: 1, situation: "Reports", advice: "24-hour times", polarity: "do",
  source: "user_correction", status: "active", pinned: false, text: "Reports → 24-hour times", recalled: 3, followed: 2,
  succeeded: 2, failed: 0, evidence: {}, last_used_at: null, created_at: "", updated_at: "", ...over });
const scoped = { scope: { folder: FOLDER } };

const show = async (rows: Lesson[]) => {
  vi.spyOn(lessonsApi, "list").mockResolvedValue(rows);
  render(<><MemoryList /><ConfirmHost /></>);
  await screen.findByTestId("learned-practices");
};
/** Whether `later` comes after `earlier` in the page. */
const follows = (later: Element, earlier: Element) =>
  Boolean(earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING);

beforeEach(async () => {
  await i18n.changeLanguage("en");
  vi.spyOn(companionApi, "memories").mockResolvedValue([]);
  vi.spyOn(companionApi, "proposals").mockResolvedValue([]);
  vi.spyOn(companionApi, "projects").mockResolvedValue([]);
  vi.spyOn(companionApi, "noticedEarlier").mockResolvedValue({ count: 0 });
});
afterEach(async () => { cleanup(); vi.restoreAllMocks(); await i18n.changeLanguage("en"); });

describe("the tag on a practice's row", () => {
  it("names the folder, in the mono font, first in the meta line", async () => {
    await show([lesson({ id: 1, ...scoped })]);
    const tag = within(screen.getByTestId("practice-1")).getByTestId("practice-scope");
    expect(tag.textContent).toBe(`Applies only in ${FOLDER}`);
    expect(within(tag).getByText(FOLDER).className).toContain("font-mono");
    expect(follows(within(screen.getByTestId("practice-1")).getByText("Your correction"), tag)).toBe(true);
  });
  it("reads in Chinese with the folder inside the sentence", async () => {
    await i18n.changeLanguage("zh");
    await show([lesson({ id: 1, ...scoped })]);
    expect(screen.getByTestId("practice-scope").textContent).toBe(`只在 ${FOLDER} 生效`);
  });
  it("a practice for everywhere shows nothing extra, whether scope is null or missing", async () => {
    await show([lesson({ id: 1, scope: null }), lesson({ id: 2 })]);
    expect(screen.getByTestId("practice-1")).toBeInTheDocument();
    expect(screen.getByTestId("practice-2")).toBeInTheDocument();
    expect(screen.queryByTestId("practice-scope")).toBeNull();
    expect(screen.getByTestId("learned-practices")).not.toHaveTextContent("Applies only in");
  });
  it("only the scoped row has it, with its own folder", async () => {
    await show([lesson({ id: 1, ...scoped }), lesson({ id: 2, scope: null }), lesson({ id: 3, scope: { folder: "/Volumes/Work/site" } })]);
    expect(within(screen.getByTestId("practice-1")).getByTestId("practice-scope")).toHaveTextContent(FOLDER);
    expect(within(screen.getByTestId("practice-2")).queryByTestId("practice-scope")).toBeNull();
    expect(within(screen.getByTestId("practice-3")).getByTestId("practice-scope")).toHaveTextContent("/Volumes/Work/site");
  });
  it("a retired, a stopped and a waiting row show it too; it comes before a reason tag", async () => {
    await show([
      lesson({ id: 3, status: "archived", ...scoped }),
      lesson({ id: 6, status: "stale", not_in_effect: "failed_repeatedly", ...scoped }),
      lesson({ id: 7, status: "proposed", not_in_effect: "conflicts", evidence: { not_in_effect: "conflicts" }, ...scoped }),
    ]);
    fireEvent.click(screen.getByText("Retired (1)"));
    expect(within(screen.getByTestId("practice-3")).getByTestId("practice-scope")).toHaveTextContent(`Applies only in ${FOLDER}`);
    expect(within(screen.getByTestId("practice-6")).getByTestId("practice-scope")).toHaveTextContent(FOLDER);
    const waiting = screen.getByTestId("practice-7");
    const reason = within(waiting).getByText(i18n.t("companion.whyShort_conflicts"));
    expect(follows(reason, within(waiting).getByTestId("practice-scope"))).toBe(true);
  });
});

describe("the hint under the current practices", () => {
  it("shows when an active row has a scope, right after the current block", async () => {
    await show([lesson({ id: 1, ...scoped }), lesson({ id: 2, scope: null }),
      lesson({ id: 7, status: "proposed", not_in_effect: "conflicts", evidence: { not_in_effect: "conflicts" } })]);
    const hint = screen.getByText(HINT_EN);
    expect(follows(hint, screen.getByTestId("practice-1"))).toBe(true);
    expect(follows(screen.getByTestId("practices-not-in-effect"), hint)).toBe(true);
  });
  it("reads in Chinese", async () => {
    await i18n.changeLanguage("zh");
    await show([lesson({ id: 1, ...scoped })]);
    expect(screen.getByText(HINT_ZH)).toBeInTheDocument();
  });
  it("is not there when no row has a scope", async () => {
    await show([lesson({ id: 1, scope: null }), lesson({ id: 2 })]);
    expect(screen.queryByText(HINT_EN)).toBeNull();
  });
  it("a scoped row that is not active does not bring it, even with an unscoped active one", async () => {
    await show([lesson({ id: 1, scope: null }), lesson({ id: 3, status: "archived", ...scoped })]);
    fireEvent.click(screen.getByText("Retired (1)"));
    expect(within(screen.getByTestId("practice-3")).getByTestId("practice-scope")).toBeInTheDocument();
    expect(screen.queryByText(HINT_EN)).toBeNull();
  });
  it("nor does a stopped or a waiting one", async () => {
    await show([lesson({ id: 6, status: "stale", not_in_effect: "failed_repeatedly", ...scoped }),
      lesson({ id: 7, status: "proposed", not_in_effect: "conflicts", evidence: { not_in_effect: "conflicts" }, ...scoped })]);
    expect(screen.getAllByTestId("practice-scope")).toHaveLength(2);
    expect(screen.queryByText(HINT_EN)).toBeNull();
  });
});

describe("the turn-on and Restore sheet", () => {
  const openSheet = async (id: number, label: string) => {
    const button = within(screen.getByTestId(`practice-${id}`)).getByText(label);
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);
    return screen.findByTestId("practice-open-sheet");
  };
  it("says where it applies, after what to do and before the source", async () => {
    await show([lesson({ id: 7, status: "proposed", not_in_effect: "conflicts", evidence: { not_in_effect: "conflicts" }, ...scoped })]);
    const sheet = within(await openSheet(7, "View and turn on"));
    const where = sheet.getByText("Where it applies");
    expect(where.nextElementSibling?.textContent).toBe(FOLDER);
    expect(where.nextElementSibling?.className).toContain("font-mono");
    expect(follows(where, sheet.getByText("What to do"))).toBe(true);
    expect(follows(sheet.getByText(/^Source:/), where)).toBe(true);
  });
  it("Restore on a retired one says so too, in Chinese", async () => {
    await i18n.changeLanguage("zh");
    await show([lesson({ id: 3, status: "archived", polarity: "avoid", ...scoped })]);
    fireEvent.click(screen.getByText("已不再用（1）"));
    const sheet = within(await openSheet(3, "恢复"));
    expect(sheet.getByText("在哪里用").nextElementSibling?.textContent).toBe(FOLDER);
    expect(follows(sheet.getByText("在哪里用"), sheet.getByText("别这样做"))).toBe(true);
  });
  it("has no such line for a practice for everywhere", async () => {
    await show([lesson({ id: 7, status: "proposed", scope: null, not_in_effect: "conflicts", evidence: { not_in_effect: "conflicts" } }),
      lesson({ id: 8, status: "proposed", not_in_effect: "conflicts", evidence: { not_in_effect: "conflicts" } })]);
    const first = await openSheet(7, "View and turn on");
    expect(first).toHaveTextContent("What to do");
    expect(first).not.toHaveTextContent("Where it applies");
    fireEvent.click(screen.getByText("Not now"));
    await waitFor(() => expect(screen.queryByTestId("practice-open-sheet")).toBeNull());
    expect(await openSheet(8, "View and turn on")).not.toHaveTextContent("Where it applies");
  });
});
