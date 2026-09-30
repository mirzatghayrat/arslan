import { afterEach, describe, expect, it } from "vitest";
import i18n from "../i18n";
import { ApiError } from "../api/client";
import { evidenceLines, evidencePath, groupEvidence, proactiveErrorText, titleOf } from "../lib/proactive";

const t = i18n.getFixedT("en");
afterEach(() => { void i18n.changeLanguage("en"); });

describe("titles", () => {
  it("fills the item's own parameters", () => {
    expect(titleOf(t, { title_key: "title.web_change", params: { label: "Pricing" } })).toBe("“Pricing” changed");
    expect(titleOf(t, { title_key: "title.scheduled_problem", params: { name: "Digest" } })).toBe("Scheduled task “Digest” needs attention");
  });

  it("uses the plural form for counts", () => {
    const folder = (count: number) => titleOf(t, { title_key: "title.folder_change", params: { label: "Inbox", count } });
    expect(folder(1)).toBe("1 new file in “Inbox”");
    expect(folder(3)).toBe("3 new files in “Inbox”");
  });

  it("follows the chosen language", () => {
    const fr = i18n.getFixedT("fr");
    expect(titleOf(fr, { title_key: "title.web_change", params: { label: "Tarifs" } })).toBe("« Tarifs » a changé");
    const zh = i18n.getFixedT("zh");
    expect(titleOf(zh, { title_key: "title.folder_change", params: { label: "收件", count: 2 } })).toBe("「收件」里有 2 个新文件");
  });
});

describe("evidence", () => {
  it("picks the wording for a schedule that is paused rather than merely failing", () => {
    expect(evidencePath({ key: "sched.state", params: { paused: true } })).toBe("sched.state.paused");
    expect(evidencePath({ key: "sched.state", params: { paused: false } })).toBe("sched.state.failing");
    expect(evidencePath({ key: "web.changed", params: {} })).toBe("web.changed");
    const [paused, failing] = evidenceLines(t, "en", [
      { key: "sched.state", params: { name: "Digest", failures: 3, paused: true } },
      { key: "sched.state", params: { name: "Digest", failures: 2, paused: false } }]);
    expect(paused.text).toBe("“Digest” failed 3 times in a row and was paused.");
    expect(failing.text).toBe("“Digest” has failed 2 times in a row.");
  });

  it("keeps outside text in `quote`, separate from the sentence", () => {
    const [line] = evidenceLines(t, "en", [{ key: "web.added", params: {}, quote: "Pro plan: $12" }]);
    expect(line).toEqual({ key: "web.added", text: "Added", quote: "Pro plan: $12" });
  });

  it("names why a job stopped, including a reason it has no special words for", () => {
    const [known, other] = evidenceLines(t, "en", [
      { key: "job.reason.task_budget_exhausted", params: { at: "2026-09-30T10:00:00" } },
      { key: "job.reason.other", params: {} }]);
    expect(known.text).toBe("It used up its budget before finishing.");
    expect(other.text).toBe("It stopped before finishing.");
  });

  it("counts in the plural and never prints a raw key or a raw placeholder", () => {
    const lines = evidenceLines(t, "en", [
      { key: "brief.open", params: { count: 1, kinds: { web_change: 1 } } },
      { key: "brief.running", params: { count: 4 } },
      { key: "folder.new", params: { label: "Inbox", count: 2 } },
      { key: "sched.run", params: { at: "2026-09-30T09:15:00" }, quote: "timeout" }]);
    expect(lines.map((l) => l.text).slice(0, 3)).toEqual(["1 item open in this inbox.", "4 jobs running in the background.", "Files that appeared since the last check:"]);
    for (const line of lines) { expect(line.text).not.toMatch(/\{\{|proactive\./); }
    expect(lines[3].text).toMatch(/^A failed run, /);
  });
});

describe("errors", () => {
  it("says what the server said, in words", () => {
    expect(proactiveErrorText(t, "item", new ApiError("already_handled", 409))).toBe("Already handled. The list was refreshed.");
    expect(proactiveErrorText(t, "settings", new ApiError("invalid_url", 422))).toBe("Use a public https address (port 443).");
  });

  it("falls back to an honest generic line, never a status code", () => {
    expect(proactiveErrorText(t, "item", new ApiError("HTTP 500", 500))).toBe("Something went wrong.");
    expect(proactiveErrorText(t, "settings", new ApiError("a_code_nobody_translated", 422))).toBe("Something went wrong.");
  });

  it("treats a dead connection as unreachable", () => {
    expect(proactiveErrorText(t, "item", new TypeError("Failed to fetch"))).toBe("Couldn't reach the service.");
  });

  it("scopes codes: a settings code is not an item code", () => {
    expect(proactiveErrorText(t, "item", new ApiError("invalid_url", 422))).toBe("Something went wrong.");
  });
});

describe("grouping", () => {
  it("says a repeated label once, with every quote under it, and keeps different labels apart", () => {
    const lines = evidenceLines(t, "en", [
      { key: "web.changed", params: { added: 2, removed: 1, url: "https://example.com/r" } },
      { key: "web.added", params: {}, quote: "v2.12.0" }, { key: "web.added", params: {}, quote: "Security fix" },
      { key: "web.removed", params: {}, quote: "v2.11.1" }]);
    expect(groupEvidence(lines)).toEqual([
      { key: "web.changed", text: "+2 / −1 lines · https://example.com/r", quotes: [] },
      { key: "web.added", text: "Added", quotes: ["v2.12.0", "Security fix"] },
      { key: "web.removed", text: "Removed", quotes: ["v2.11.1"] }]);
  });

  it("folds new file names under the folder line in every language", () => {
    for (const language of ["en", "zh", "ja", "es", "de", "fr"]) {
      const lines = evidenceLines(i18n.getFixedT(language), language, [
        { key: "folder.new", params: { label: "Inbox", count: 2 } },
        { key: "folder.file", params: {}, quote: "a.pdf" }, { key: "folder.file", params: {}, quote: "b.pdf" }]);
      const groups = groupEvidence(lines);
      expect(groups, language).toHaveLength(1);
      expect(groups[0].quotes).toEqual(["a.pdf", "b.pdf"]);
    }
  });

  it("never merges lines that are apart, even with the same words", () => {
    const lines = evidenceLines(t, "en", [
      { key: "web.added", params: {}, quote: "a" }, { key: "web.removed", params: {}, quote: "b" }, { key: "web.added", params: {}, quote: "c" }]);
    expect(groupEvidence(lines).map((g) => g.quotes)).toEqual([["a"], ["b"], ["c"]]);
  });
});
