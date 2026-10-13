/** 0.1.61 release: every public claim about how long a card waits.
 *
 *  A card waits 30 minutes (`approvals.TIMEOUT_S = 1800`) and running out is not a no. Before 0.1.61 it was declined after 300 s.
 *  The READMEs, the technical docs (source chapter and built page, six languages) and the project page go live on merge, and the
 *  app ships later, so each says what changed: "since 0.1.61: 30 minutes, and running out is not a no; earlier versions: 300 s",
 *  the way the support page does. The notification the Mac shows when an action is waiting ships with the app, so it just says
 *  30 minutes. support/index.html is pinned in card-words.test.tsx. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const LANGS = ["en", "zh", "ja", "es", "de", "fr", "tr"] as const;
type Lang = (typeof LANGS)[number];
const repo = (path: string) => readFileSync(resolve(__dirname, "../../..", path), "utf8");

/** The old spellings of the claim, in any language: a number of seconds or minutes next to the word for waiting or being declined. */
const OLD_CLAIM = /\b300 ?(s|seconds|Sekunden|segundos|saniye)\b|300 ?秒|(?<!\d)5 ?(minutes|Minuten|minutos)\b|(?<!\d)5 ?分(钟|で|以内)?|declined at 5:00/;

// ── the READMEs ──────────────────────────────────────────────────────────────────────────────────────────────────

/** The README file of each language, and the end of its "Your Mac in your pocket" row. `earlier` is the clause that may name 300 s. */
const README: Record<Exclude<Lang, "fr">, { file: string; tail: string; earlier: string }> = {
  en: { file: "README.md", earlier: "earlier versions declined it after 300 s",
    tail: "the first answer wins. An unanswered card waits 30 minutes, and running out is not a no (since 0.1.61; earlier versions declined it after 300 s). |" },
  zh: { file: "README.zh-CN.md", earlier: "更早的版本在 300 秒后自动拒绝",
    tail: "谁先点算谁的；无人回应的卡会等 30 分钟，时间到了也不算拒绝（0.1.61 起；更早的版本在 300 秒后自动拒绝）。 |" },
  ja: { file: "README.ja.md", earlier: "それ以前のバージョンは 300 秒で拒否",
    tail: "先に答えた方が有効。応答のないカードは 30 分間待ち、時間切れは拒否ではありません（0.1.61 以降。それ以前のバージョンは 300 秒で拒否）。 |" },
  es: { file: "README.es.md", earlier: "las versiones anteriores la rechazaban a los 300 s",
    tail: "gana la primera respuesta. Una tarjeta sin respuesta espera 30 minutos, y que se agote el plazo no es un no (desde 0.1.61; las versiones anteriores la rechazaban a los 300 s). |" },
  de: { file: "README.de.md", earlier: "frühere Versionen lehnten sie nach 300 s ab",
    tail: "die erste Antwort gilt. Eine unbeantwortete Karte wartet 30 Minuten, und dass die Zeit abläuft, ist kein Nein (seit 0.1.61; frühere Versionen lehnten sie nach 300 s ab). |" },
  tr: { file: "README.tr.md", earlier: "önceki sürümler 300 saniye sonra reddederdi",
    tail: "ilk cevap geçerlidir. Yanıtsız kalan bir kart 30 dakika bekler ve sürenin dolması bir ret sayılmaz (0.1.61'den itibaren; önceki sürümler 300 saniye sonra reddederdi). |" },
};

describe("the READMEs say a card waits 30 minutes since 0.1.61, and 300 s only for earlier versions", () => {
  it.each(Object.keys(README) as (keyof typeof README)[])("%s", (lang) => {
    const { file, tail, earlier } = README[lang];
    const row = repo(file).split("\n").find((line) => line.includes("iCloud") && line.includes("0.1.61"));
    expect(row, file).toBeDefined();
    expect(row!.endsWith(tail), file).toBe(true);
    expect(row!.replace(earlier, ""), file).not.toMatch(OLD_CLAIM);              // 300 s is named only inside the earlier-versions clause
  });

  it("the guard itself: the old rows are caught", () => {
    expect("an unanswered card is declined after 300 s. |").toMatch(OLD_CLAIM);
    expect("eine unbeantwortete Karte wird nach 300 s abgelehnt. |").toMatch(OLD_CLAIM);
    expect("无人回应的卡 300 秒后自动拒绝。 |").toMatch(OLD_CLAIM);
    expect("yanıtsız kalan bir kart 300 saniye sonra reddedilir. |").toMatch(OLD_CLAIM);
    expect("una tarjeta sin respuesta se rechaza a los 300 s. |").toMatch(OLD_CLAIM);
    expect("300 秒応答がなければ拒否されます。 |").toMatch(OLD_CLAIM);
  });
});

// ── the technical docs: chapter 9, source and built page, six languages ──────────────────────────────────────────

/** The sentence of docs-site/sections/<lang>/09-security.html (line 20) about an approval card that nobody answers. */
const DOCS: Record<Exclude<Lang, "fr">, { sentence: string; earlier: string }> = {
  en: { sentence: "unanswered, it stays open for 30 minutes, and running out is not a no (since 0.1.61; earlier versions: it expired after 300 seconds).",
    earlier: "earlier versions: it expired after 300 seconds" },
  zh: { sentence: "无人回答则保持开启 30 分钟，时间到了也不算拒绝（自 0.1.61 起；更早的版本在 300 秒后过期）。",
    earlier: "更早的版本在 300 秒后过期" },
  ja: { sentence: "回答がなければ 30 分間開いたままで、時間切れは拒否ではありません（0.1.61 以降。それ以前のバージョンでは 300 秒で期限切れ）。",
    earlier: "それ以前のバージョンでは 300 秒で期限切れ" },
  es: { sentence: "Sin respuesta, permanecen abiertas 30 minutos, y que se agote el plazo no es un no (desde 0.1.61; versiones anteriores: caducaban a los 300 segundos).",
    earlier: "versiones anteriores: caducaban a los 300 segundos" },
  de: { sentence: "Ohne Antwort bleibt sie 30 Minuten offen, und dass die Zeit abläuft, ist kein Nein (seit 0.1.61; frühere Versionen: Ablauf nach 300 Sekunden).",
    earlier: "frühere Versionen: Ablauf nach 300 Sekunden" },
  tr: { sentence: "Yanıt gelmezse kart 30 dakika açık kalır ve sürenin dolması bir ret sayılmaz (0.1.61'den itibaren; önceki sürümlerde 300 saniye sonra geçersizleşirdi).",
    earlier: "önceki sürümlerde 300 saniye sonra geçersizleşirdi" },
};
const BUILT: Record<Exclude<Lang, "fr">, string> = {
  en: "docs/docs/index.html", zh: "docs/docs/zh/index.html", ja: "docs/docs/ja/index.html",
  es: "docs/docs/es/index.html", de: "docs/docs/de/index.html", tr: "docs/docs/tr/index.html",
};

describe("the technical docs' security chapter says the same, in the source and in the built page", () => {
  it.each(Object.keys(DOCS) as (keyof typeof DOCS)[])("%s", (lang) => {
    const { sentence, earlier } = DOCS[lang];
    for (const file of [`docs-site/sections/${lang}/09-security.html`, BUILT[lang]]) {
      const page = repo(file);
      expect(page, file).toContain(sentence);
      // Only the approval card's sentence is in question: no other "300 seconds" about it is left once the earlier-versions clause is taken out.
      const paragraph = page.split("\n").find((line) => line.includes(sentence))!;
      expect(paragraph.replace(earlier, ""), file).not.toMatch(OLD_CLAIM);
    }
  });
});

// ── the project page ─────────────────────────────────────────────────────────────────────────────────────────────

describe("the project page says 30 minutes since 0.1.61, and 300 s only as what came before", () => {
  const page = repo("docs/index.html");

  it("the stat, the lane, the policy chip and the race say it", () => {
    expect(page).toContain("<b>30 min</b><span>to approve, Mac or iPhone (0.1.61+; 300 s before)</span>");
    expect(page).toContain("waits for you · 30 min (0.1.61+)");
    expect(page).toContain("approvals.py · 30 min since 0.1.61 (300 s before)");
    expect(page).toContain('<span>nobody answers</span><span title="Earlier versions declined it at 5:00">30:00, not a no · 0.1.61+</span>');
  });

  it("no bare 300 s or 5:00 is left on it", () => {
    const rest = page
      .replace("(0.1.61+; 300 s before)", "").replace("(300 s before)", "").replace("Earlier versions declined it at 5:00", "");
    expect(rest).not.toMatch(/\b300 ?s\b|declined at 5:00|\b5:00\b/);
  });
});

// ── the notification the Mac shows ───────────────────────────────────────────────────────────────────────────────

const NOTICE: Record<Exclude<Lang, "tr">, string> = {
  en: "An action is waiting for you. It waits 30 minutes; running out is not a no.",
  zh: "有一个动作在等你确认。最多等 30 分钟；时间到了也不算拒绝。",
  ja: "操作があなたの確認を待っています。最長 30 分待機し、時間切れは拒否にはなりません。",
  es: "Una acción espera tu respuesta. Espera hasta 30 minutos; si se agota el plazo, no cuenta como un no.",
  de: "Eine Aktion wartet auf dich. Sie wartet bis zu 30 Minuten; läuft die Zeit ab, ist das kein Nein.",
  fr: "Une action vous attend. Elle attend jusqu’à 30 minutes ; sans réponse, ce n’est pas un refus.",
};

describe("the notification for a waiting action says 30 minutes and not a no, never 'declined after 5 minutes'", () => {
  const catalog = JSON.parse(repo("desktop/src-tauri/native_messages.json")) as Record<string, Record<string, string>>;
  it.each(Object.keys(NOTICE) as (keyof typeof NOTICE)[])("%s", (lang) => {
    expect(catalog[lang].notify_approval_body).toBe(NOTICE[lang]);
    expect(catalog[lang].notify_approval_body).not.toMatch(OLD_CLAIM);
  });
});
