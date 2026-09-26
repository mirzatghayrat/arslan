import { describe, expect, it } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import { formatUiDate, formatUiDateTime, formatUiTime, uiDate, uiLocale } from "../lib/localeFormatting";
import { threadDisplayTitle } from "../lib/threadTitles";
import { makeFreshThread, persistThreads, restoreThreads, mergeServerConversations } from "../lib/sessionPersistence";

describe("localized runtime values", () => {
  it.each(SUPPORTED_LANGUAGES)("formats dates and marked defaults using %s, not browser language", async language => {
    await i18n.changeLanguage(language);
    const date = new Date("2026-09-15T16:05:00Z");
    expect(formatUiTime(date, language)).toBe(date.toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" }));
    expect(formatUiDate(date, language)).toBe(date.toLocaleDateString(language));
    expect(formatUiDateTime(date, language)).toBe(date.toLocaleString(language, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }));
    expect(threadDisplayTitle(makeFreshThread(1), key => String(i18n.t(key)))).toBe(i18n.t("workspace.newConversation"));
    expect(threadDisplayTitle({ title: "New Session" }, key => String(i18n.t(key)))).toBe("New Session");
    expect(threadDisplayTitle({ title: "My title", defaultTitle: true }, key => String(i18n.t(key)))).toBe("My title");
    await i18n.changeLanguage("en");
  });
  it("preserves explicit UTC and treats naive backend timestamps as UTC", () => {
    expect(uiDate("2026-09-15T16:05:00").getTime()).toBe(Date.parse("2026-09-15T16:05:00Z"));
    expect(uiDate("2026-09-15T16:05:00+08:00").getTime()).toBe(Date.parse("2026-09-15T08:05:00Z"));
    expect(formatUiDate("not a date", "de")).toBe("");
    expect(uiLocale("fr-FR")).toBe("fr");
    expect(uiLocale("unsupported")).toBe("en");
  });
  it("round-trips only a valid generated-title marker and clears it for server titles", () => {
    const fresh = makeFreshThread(123);
    persistThreads([fresh], fresh.id);
    expect(restoreThreads().threads[0].defaultTitle).toBe(true);
    persistThreads([{ ...fresh, title: "A title chosen by me" }], fresh.id);
    expect(restoreThreads().threads[0].defaultTitle).toBeUndefined();
    const merged = mergeServerConversations([fresh], [{
      conversation_id: fresh.id, title: "Real conversation", message_count: 1,
    }]);
    expect(merged[0].title).toBe("Real conversation");
    expect(merged[0].defaultTitle).toBeUndefined();
    localStorage.clear();
  });
});
