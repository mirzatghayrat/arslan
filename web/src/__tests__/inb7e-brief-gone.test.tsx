/** INB7-e (v0.1.64; the user's Q9, #605 review F2): the morning brief went everywhere. The window has no brief kind, no days for
 *  one, no words for one in any language, no setting for one, and a reminder card has no read-only "Got it" door that only the
 *  brief used. The server reads past a brief row stored before (tests/server/test_proactive_api.py); were one to arrive anyway,
 *  its card still draws, with the fallback icon. */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import type { ProactiveKind } from "../api/proactive";
import { ReminderCard } from "../components/proactive/reminders";
import { FIELD_HOMES } from "../components/settings/sectionRegistry";
import { KEPT_DAYS } from "../lib/proactive";
import { proactiveMessages } from "../locales/proactive";

afterEach(cleanup);

describe("the morning brief is gone from the window", () => {
  it("has no kind, and no days a handled one keeps its row", () => {
    // @ts-expect-error: "brief" is no ProactiveKind any more
    const retired: ProactiveKind = "brief";
    expect(retired).toBe("brief");
    expect(Object.keys(KEPT_DAYS)).not.toContain("brief");
  });

  it.each(SUPPORTED_LANGUAGES)("has no words for it in %s", (language) => {
    const messages = proactiveMessages[language as keyof typeof proactiveMessages] as unknown as Record<string, Record<string, unknown>>;
    expect(messages.kind).not.toHaveProperty("brief");
    expect(messages.title).not.toHaveProperty("brief");
    expect(messages.evidence).not.toHaveProperty("brief");
    expect(Object.keys(messages.settings).filter((key) => key.startsWith("brief"))).toEqual([]);
    expect(messages.item).not.toHaveProperty("gotIt");
  });

  it("has no setting for it", () => {
    expect(Object.keys(FIELD_HOMES).filter((key) => key.includes("brief"))).toEqual([]);
  });

  it("a card of a kind it does not know still draws, and offers no read-only Got it", async () => {
    await i18n.changeLanguage("en");
    const item = { id: 9, kind: "brief", title_key: "title.brief", params: {}, evidence: [], goal: "", priority: "normal",
      status: "new", diagnosis: null, conversation_id: null, job_id: null, created_at: "2026-11-01T09:00:00", snooze_until: null };
    const doors = { onDo: vi.fn(), onSnooze: vi.fn(), onDismiss: vi.fn(), onOpenConversation: vi.fn() };
    render(<ReminderCard item={item as never} busy={false} language="en" {...doors} />);
    const card = screen.getByTestId("proactive-item-9");
    expect(card.textContent).not.toMatch(/Got it|gotIt/);
    expect(screen.getByRole("button", { name: "Not useful" })).toBeTruthy();       // the read-only card had no way to silence it
  });
});
