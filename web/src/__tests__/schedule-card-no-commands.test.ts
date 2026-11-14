import { describe, expect, it } from "vitest";
import de from "../locales/de.json";
import en from "../locales/en.json";
import es from "../locales/es.json";
import fr from "../locales/fr.json";
import ja from "../locales/ja.json";
import zh from "../locales/zh.json";

/**
 * ASK1-b (v0.1.64): a scheduled task's own run runs commands that wouldn't need the user's OK, inside the sandbox;
 * anything that would is refused and listed (tests/server/test_ask1b_scheduled_commands.py). Only the heartbeat and
 * a sub-session's turn with nobody to ask still run no command (tests/server/test_scheduled_run_no_command.py), and
 * neither has a schedule card. The card's line about what an unattended run may do says what runs, in every language,
 * and no longer says that nothing does; the Scheduled page's one-time note says the same.
 */
const said: Record<string, [string, string, string, string]> = {
  en: [en.schedgrant.unattended, "run commands that wouldn't need your OK", "refused and listed", "don't run commands"],
  zh: [zh.schedgrant.unattended, "不需要你确认的命令会在沙盒里运行", "会被拒绝，并列在", "不运行命令"],
  ja: [ja.schedgrant.unattended, "確認が要らないコマンドはサンドボックスの中で実行", "拒否され", "コマンドは実行しません"],
  de: [de.schedgrant.unattended, "führen sie in der Sandbox aus", "abgelehnt und", "Befehle führen sie nicht aus"],
  fr: [fr.schedgrant.unattended, "lancent dans le bac à sable les commandes", "refusé et listé", "ne lancent pas de commandes"],
  es: [es.schedgrant.unattended, "ejecutan en el entorno aislado los comandos", "se rechaza y aparece", "no ejecutan comandos"],
};

describe("the schedule card says a scheduled run runs commands that need no OK, in the sandbox", () => {
  it.each(Object.entries(said))("%s", (_lang, [text, runs, refused, none]) => {
    expect(text).toContain(runs);
    expect(text).toContain(refused);
    expect(text).not.toContain(none);
  });

  it.each(Object.entries({ en, zh, ja, de, fr, es }))("%s: the Scheduled page's note names the setting that turns it off", (_lang, d) => {
    expect(d.scheduledPage.commandsNoteBody).toContain(d.settings.shellPolicyAskAll);
  });
});
