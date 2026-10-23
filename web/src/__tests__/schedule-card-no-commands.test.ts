import { describe, expect, it } from "vitest";
import de from "../locales/de.json";
import en from "../locales/en.json";
import es from "../locales/es.json";
import fr from "../locales/fr.json";
import ja from "../locales/ja.json";
import zh from "../locales/zh.json";

/**
 * v0.1.63 (the user's decision until S2a-3 lands in v0.1.64): a scheduled run runs no command
 * (tests/server/test_scheduled_run_no_command.py). The schedule card's line about what an unattended
 * run may do says so in every language, and no longer offers commands in the sandbox.
 */
const said: Record<string, [string, string]> = {
  en: [en.schedgrant.unattended, "don't run commands"],
  zh: [zh.schedgrant.unattended, "不运行命令"],
  ja: [ja.schedgrant.unattended, "コマンドは実行しません"],
  de: [de.schedgrant.unattended, "Befehle führen sie nicht aus"],
  fr: [fr.schedgrant.unattended, "ne lancent pas de commandes"],
  es: [es.schedgrant.unattended, "no ejecutan comandos"],
};

describe("the schedule card says a scheduled run runs no commands", () => {
  it.each(Object.entries(said))("%s", (_lang, [text, phrase]) => {
    expect(text).toContain(phrase);
  });

  it("and no longer offers commands in the sandbox", () => {
    expect(en.schedgrant.unattended).not.toMatch(/run commands in the sandbox/);
  });
});
