/** INB9-a (v0.1.64): a conversation waiting on a 👀 a job's acceptance sheet left (the server's `waiting_on: "glance"`)
 *  says so: an eye in the amber ring, ranked after a card and an away entry and before a stopped job's reminder. */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { resolvedLanguage: "en", language: "en" } }) }));

import ConversationGlyph from "../components/ConversationGlyph";
import { metaFrom, mostUrgent, waitingLabel } from "../lib/conversationMeta";
import de from "../locales/de.json";
import en from "../locales/en.json";
import es from "../locales/es.json";
import fr from "../locales/fr.json";
import ja from "../locales/ja.json";
import zh from "../locales/zh.json";

afterEach(cleanup);

describe("a row waiting on a glance", () => {
  it("reads as something to look at, drawn as an eye", () => {
    const meta = metaFrom([{ conversation_id: "g", kind: "task", state: "waiting", waiting_on: "glance" }] as never);
    expect(meta.g.waitingOn).toBe("glance");
    render(<ConversationGlyph meta={meta.g} />);
    const glyph = screen.getByRole("img", { name: "sidebar.glyph.waiting_glance" });
    expect(glyph.querySelector(".lucide-eye")).toBeTruthy();
    expect(glyph.querySelector(".lucide-bell")).toBeNull();
  });

  it("ranks after a card and an away entry, before a reminder", () => {
    expect(mostUrgent(["reminder", "glance"])).toBe("glance");
    expect(mostUrgent(["glance", "away"])).toBe("away");
    expect(mostUrgent(["glance", "card"])).toBe("card");
    expect(waitingLabel("glance")).toBe("waiting_glance");
  });

  it("has words in every language", () => {
    for (const words of [en, zh, ja, es, de, fr]) {
      expect((words as { sidebar: { glyph: Record<string, string> } }).sidebar.glyph.waiting_glance).toBeTruthy();
    }
  });
});
