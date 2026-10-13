/** 0.1.61 §A4 (PR 2b Task 7): the words about a card that nobody answers.
 *
 *  A card waits 30 minutes, and running out is never a no. Settings › Desktop used to say a card is "declined after 5 minutes"
 *  in every app language, the support page and the Bridge protocol said five minutes too. And the notice that comes up when a
 *  card runs out ("…so it was not done… Arslan will tell you what is waiting") is wrong for a proposal to enrol a machine or to
 *  connect a server: those never wait on the server, nothing is held for them, and Arslan has nothing to tell. They get a line
 *  of their own, in six languages. */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k) }),
}));

import AskSlot from "../components/AskSlot";
import { initialArslanState, useArslanStore } from "../stores/arslanStore";
import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import es from "../locales/es.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";

const LANGS = ["en", "zh", "ja", "es", "de", "fr"] as const;
type Lang = (typeof LANGS)[number];
const LOCALES = { en, zh, ja, es, de, fr };
const repo = (path: string) => readFileSync(resolve(__dirname, "../../..", path), "utf8");
/** A doc's text with its line breaks and indents read as single spaces (what a reader sees). */
const flowed = (text: string) => text.replace(/\s+/g, " ");

// ── Settings › Desktop ────────────────────────────────────────────────────────────────────────────────────────

/** What each language said: "declined after 5 minutes". */
const FIVE_MINUTES: Record<Lang, RegExp> = {
  en: /declined after 5 minutes/, zh: /5 分钟没回应会被拒绝/, ja: /5 分で拒否されます/,
  es: /se rechazan a los 5 minutos/, de: /nach 5 Minuten werden sie abgelehnt/, fr: /refusées au bout de 5 minutes/,
};
/** What they say now: up to 30 minutes, and not answering is not a no. */
const NOT_A_NO: Record<Lang, RegExp> = {
  en: /not a no/, zh: /不算拒绝/, ja: /拒否にはなりません/, es: /no cuenta como un no/, de: /ein Nein ist das nicht/, fr: /sans que ce soit un refus/,
};

describe("Settings › Desktop says how long a card waits", () => {
  it.each(LANGS)("%s: up to 30 minutes, and running out is not a no — never 'declined after 5 minutes'", (lang) => {
    const lede = LOCALES[lang].settings.desktopLede;
    expect(lede).toMatch(/\b30\b/);
    expect(lede).toMatch(NOT_A_NO[lang]);
    expect(lede).not.toMatch(FIVE_MINUTES[lang]);
    expect(lede).not.toMatch(/\b5 ?(minutes|分钟|分|Minuten|minutos)/);
  });

  it("the guard itself: each language's old wording is caught by its pattern", () => {
    const old: Record<Lang, string> = {
      en: "(they are declined after 5 minutes)", zh: "（5 分钟没回应会被拒绝）", ja: "（5 分で拒否されます）",
      es: "(se rechazan a los 5 minutos)", de: "(nach 5 Minuten werden sie abgelehnt)", fr: "(refusées au bout de 5 minutes)",
    };
    for (const lang of LANGS) {
      expect(old[lang], lang).toMatch(FIVE_MINUTES[lang]);
      expect(old[lang], lang).not.toMatch(NOT_A_NO[lang]);
    }
  });
});

describe("the support page and the Bridge protocol", () => {
  it("the support page says a card stays open 30 minutes and running out is not a no; five minutes is only for earlier versions", () => {
    const page = repo("docs/support/index.html");
    expect(page).toContain("A card nobody answers stays open for 30 minutes, and running out is not a no");
    expect(page).toContain('<span class="tag">Mac 0.1.61+</span> Earlier versions close it after five minutes.');
    expect(page.match(/five minutes/g)).toHaveLength(1);                              // the one sentence about earlier versions
    expect(page).not.toContain("expires after five minutes");
  });

  it("the Chinese FAQ on the same page says the same, tagged — the page switches by language, and 五 is not 5", () => {
    const page = repo("docs/support/index.html");
    expect(page).toContain("没人回应的批准卡会保持开启 30 分钟，时间到了也不算拒绝：Arslan 会告诉你还有什么在等你。"
      + '<span class="tag">Mac 0.1.61+</span> 更早的版本会在五分钟后关闭它。');
    expect(page).not.toContain("五分钟后过期");
    expect(page.match(/五分钟/g)).toHaveLength(1);                                    // only the sentence about earlier versions
  });

  it("no other spelling of the old claim is left on the support page: 5 minutes, 300 s, 五分钟, 5 分钟", () => {
    const page = repo("docs/support/index.html").replace(/Earlier versions close it after five minutes\./, "").replace(/更早的版本会在五分钟后关闭它。/, "");
    expect(page).not.toMatch(/five minutes|5 minutes|5-minute|五分钟|5 分钟|5分钟|\b300 ?s\b|300 seconds|300 秒/i);
  });

  it("the protocol says an expired card answers 'expired' (30 minutes since 0.1.61), never a refusal", () => {
    const spec = flowed(repo("docs/specs/mobile-bridge-protocol.md"));
    expect(spec).toContain("a card that expired on the Mac (30 min since 0.1.61; 5 min before) answers `expired`, which is never a refusal.");
    expect(spec).not.toContain("(5 min)");
  });

  it("the protocol gives the risk words as built: perm_kind first, then the rules that were; a capability card never reaches the phone", () => {
    const raw = repo("docs/specs/mobile-bridge-protocol.md");
    const spec = flowed(raw);
    expect(spec).toContain("`money` → `payment`, `send` → `send`, `destructive` → `delete`, `outside` → `install`; any other kind keeps the rules above.");
    expect(spec).toContain("A `capability` card never reaches the phone.");
    // and the approval.request row says the same where the fields are listed
    const row = raw.split("\n").find((l) => l.startsWith("| `approval.request` |")) ?? "";
    expect(row).toContain("the card's `title` when it has one");
    expect(row).toContain("`perm_kind` decides the word first");
    expect(row).toContain("the card's own");
  });

  it("the 0.1.61 spec §A4 gives the Bridge's risk words as built, not 'everything else → write'", () => {
    const spec = repo("docs/specs/2026-10-11-0161-smooth.md");
    const bullet = flowed(spec.slice(spec.indexOf("- **The Bridge** maps the new kinds"), spec.indexOf("**One card for identical requests.**")));
    expect(bullet).toContain("money → `payment`, send → `send`, destructive → `delete`, outside → `install`");
    expect(bullet).toContain("a command card keeps its command risk, a site action is `send`, the rest is `write`");
    expect(bullet).toContain("A capability card never reaches the phone");
    expect(bullet).not.toContain("everything else → `write`");
  });
});

// ── The notice when a card runs out ───────────────────────────────────────────────────────────────────────────

const ENROLL = { type: "propose_enroll_node", call_id: "n1", name: "mini", host: "10.0.0.2", user: "me", fingerprints: ["SHA256:abc"] };
const CONNECT = { type: "propose_connect_mcp", call_id: "m1", key: "memory", label: "Memory", transport: "stdio", command: "npx", argv: [],
  url: null, env_keys: [], prerequisites: "", requires_path: false, path_placeholder: null };
const COMMAND = { type: "propose_run_command", call_id: "c1", pretty: "ls", reason: "", options: ["once", "conversation"] };
const WRITE = { type: "propose_workspace_write", call_id: "w1", workspace: "/w", action: "write_file", path: "a", options: ["once", "conversation"] };

beforeEach(() => { useArslanStore.setState(initialArslanState(), true); vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-13T10:00:00Z")); });
afterEach(() => { cleanup(); vi.useRealTimers(); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });
/** Past a card's 30 minutes and the 2 s the slot leaves it after the server has closed it. */
const runOut = () => advance(1_802_000);
const body = () => screen.getByTestId("ask-expired").textContent ?? "";

describe("the notice when a card runs out says what is true of that card", () => {
  it("a proposal to enrol a machine has its own line: nothing waits on the server, so it does not say Arslan will tell what is waiting", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(ENROLL);
    runOut();
    expect(body()).toContain("kit.expiredTitle");
    expect(body()).toContain("kit.expiredEnrollBody");
    expect(body()).not.toContain("kit.expiredBody");
    expect(body()).not.toContain("kit.expiredConnectBody");
  });

  it("a proposal to connect a server has its own line too", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(CONNECT);
    runOut();
    expect(body()).toContain("kit.expiredTitle");
    expect(body()).toContain("kit.expiredConnectBody");
    expect(body()).not.toContain("kit.expiredBody");
    expect(body()).not.toContain("kit.expiredEnrollBody");
  });

  it.each([["a command card", COMMAND], ["a write card", WRITE]])("%s keeps the line that says Arslan will tell what is waiting", (_n, card) => {
    render(<AskSlot send={vi.fn()} />);
    frame(card);
    runOut();
    expect(body()).toContain("kit.expiredBody");
    expect(body()).not.toContain("kit.expiredEnrollBody");
    expect(body()).not.toContain("kit.expiredConnectBody");
  });

  it("when a card the server waits on runs out beside a proposal, the notice keeps the line that is true of it, whichever ran out first", () => {
    render(<AskSlot send={vi.fn()} />);
    frame({ ...ENROLL });                                   // 30 minutes after it arrived
    frame({ ...COMMAND, expires_at: Date.now() / 1000 + 600 });
    advance(602_000);                                       // the command first
    expect(useArslanStore.getState().cardExpired).toBe(true);
    runOut();                                               // then the enrolment
    expect(body()).toContain("kit.expiredBody");
    expect(body()).not.toContain("kit.expiredEnrollBody");
    cleanup();
    useArslanStore.setState(initialArslanState(), true);
    render(<AskSlot send={vi.fn()} />);
    frame({ ...COMMAND, expires_at: Date.now() / 1000 + 1700 });
    frame({ ...ENROLL });
    act(() => { useArslanStore.getState().expireCard("n1"); });                // the enrolment first: the command still waits, so no notice yet
    expect(useArslanStore.getState().cardExpiredKind).toBe("enroll");
    act(() => { useArslanStore.getState().expireCard("c1"); });                // then the command
    expect(useArslanStore.getState().cardExpiredKind).toBe("ask");
    expect(body()).toContain("kit.expiredBody");
    expect(body()).not.toContain("kit.expiredEnrollBody");
  });

  it("the line goes with the notice: a later card that runs out is read fresh, not as the proposal before it", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(ENROLL);
    runOut();
    act(() => { screen.getByTestId("ask-expired-close").click(); });
    expect(screen.queryByTestId("ask-expired")).toBeNull();
    expect(useArslanStore.getState().cardExpiredKind).toBeNull();
    frame(COMMAND);
    runOut();
    expect(body()).toContain("kit.expiredBody");
    expect(body()).not.toContain("kit.expiredEnrollBody");
    // and the user coming back (a new message) lets it go the same way
    cleanup();
    useArslanStore.setState(initialArslanState(), true);
    render(<AskSlot send={vi.fn()} />);
    frame(CONNECT);
    runOut();
    act(() => { useArslanStore.getState().addUserMessage("I'm back"); });
    expect(useArslanStore.getState().cardExpiredKind).toBeNull();
    frame(WRITE);
    runOut();
    expect(body()).toContain("kit.expiredBody");
  });

  it("the server's own 'expired' for a card kind it holds reads as the default line", () => {
    render(<AskSlot send={vi.fn()} />);
    frame(COMMAND);
    frame({ type: "card_resolved", call_id: "c1", outcome: "expired" });
    expect(body()).toContain("kit.expiredBody");
    expect(useArslanStore.getState().cardExpiredKind).toBe("ask");
  });
});

const NOT_A_NO_NOTICE: Record<Lang, RegExp> = {
  en: /not a no/, zh: /不算拒绝/, ja: /拒否ではありません/, es: /No es un no/, de: /kein Nein/, fr: /pas un refus/,
};
const MACHINE: Record<Lang, RegExp> = { en: /machine/, zh: /机器/, ja: /マシン/, es: /máquina/, de: /Maschine/, fr: /machine/ };
const SERVER: Record<Lang, RegExp> = { en: /server/, zh: /服务器/, ja: /サーバー/, es: /servidor/, de: /Server/, fr: /serveur/ };

/** The default line's own sentences: "so it was not done" and "Arslan will tell you what is waiting". */
const NOT_DONE: Record<Lang, RegExp> = {
  en: /so it was not done/, zh: /所以这一步没有做/, ja: /実行していません/, es: /así que no se hizo/, de: /deshalb ist es nicht passiert/, fr: /donc rien n’a été fait/,
};
const WILL_TELL: Record<Lang, RegExp> = {
  en: /will tell you what is waiting/, zh: /会告诉你还有什么在等你/, ja: /何が待っているかは Arslan が伝えます/, es: /te dirá qué queda pendiente/,
  de: /sagt dir, was noch wartet/, fr: /vous dira ce qui attend/,
};

describe("the three lines, in six languages", () => {
  it.each(LANGS)("%s: enrol and connect each have a line of their own — 30 minutes, not a no, what was left undone — and neither claims what is not true of them", (lang) => {
    const kit = LOCALES[lang].kit;
    const lines = [kit.expiredBody, kit.expiredEnrollBody, kit.expiredConnectBody];
    expect(new Set(lines).size, `${lang}: three different lines`).toBe(3);
    // The default is the one that says "not done" and "Arslan will tell you" — the guard that the patterns bite.
    expect(kit.expiredBody).toMatch(NOT_DONE[lang]);
    expect(kit.expiredBody).toMatch(WILL_TELL[lang]);
    for (const own of [kit.expiredEnrollBody, kit.expiredConnectBody]) {
      expect(own.trim(), lang).not.toBe("");
      expect(own, lang).toMatch(/\b30\b/);
      expect(own, lang).toMatch(NOT_A_NO_NOTICE[lang]);
      expect(own, lang).not.toMatch(NOT_DONE[lang]);
      expect(own, lang).not.toMatch(WILL_TELL[lang]);
    }
  });

  it.each(LANGS)("%s: the enrol line is about the machine and the connect line about the server", (lang) => {
    const kit = LOCALES[lang].kit;
    expect(kit.expiredEnrollBody, lang).toMatch(MACHINE[lang]);
    expect(kit.expiredEnrollBody, lang).not.toMatch(SERVER[lang]);
    expect(kit.expiredConnectBody, lang).toMatch(SERVER[lang]);
    expect(kit.expiredConnectBody, lang).not.toMatch(MACHINE[lang]);
  });
});

// ── Fix round 1 ────────────────────────────────────────────────────────────────────────────────────────────────

/** What the enrol and connect lines say was NOT done. A flipped verb ("已经记住") keeps every keyword above, so these pin the negation. */
const ENROLL_NOT_DONE: Record<Lang, RegExp> = {
  en: /was not remembered/, zh: /没有记住/, ja: /記憶していません/, es: /no se recordó/, de: /nicht gemerkt/, fr: /pas été mémorisée/,
};
const CONNECT_NOT_DONE: Record<Lang, RegExp> = {
  en: /was not connected/, zh: /没有连接/, ja: /接続していません/, es: /no se conectó/, de: /nicht verbunden/, fr: /pas été connecté/,
};
/** A scheduled task never waits for an answer (spec §A4): the lede says so, after the sentence about cards that wait in the window. */
const SCHEDULED_NEVER_WAITS: Record<Lang, RegExp> = {
  en: /A scheduled task never waits for an answer/, zh: /定时任务从不等你回应/, ja: /スケジュールタスクは応答を待ちません/,
  es: /Una tarea programada nunca espera una respuesta/, de: /Eine geplante Aufgabe wartet nie auf eine Antwort/, fr: /Une tâche planifiée n’attend jamais de réponse/,
};

describe("fix round 1: the notice lines say what was left undone, and the lede does not make a scheduled task wait", () => {
  it.each(LANGS)("%s: the enrol line says the machine was NOT remembered and the connect line that the server was NOT connected", (lang) => {
    const kit = LOCALES[lang].kit;
    expect(kit.expiredEnrollBody, lang).toMatch(ENROLL_NOT_DONE[lang]);
    expect(kit.expiredConnectBody, lang).toMatch(CONNECT_NOT_DONE[lang]);
    expect(kit.expiredEnrollBody, lang).not.toMatch(CONNECT_NOT_DONE[lang]);
    expect(kit.expiredConnectBody, lang).not.toMatch(ENROLL_NOT_DONE[lang]);
  });

  it("the German lines ask Arslan again in one plain sentence, not with an adverb that also reads as 'please'", () => {
    expect(de.kit.expiredEnrollBody).not.toMatch(/Bitte Arslan/);
    expect(de.kit.expiredConnectBody).not.toMatch(/Bitte Arslan/);
    expect(de.kit.expiredEnrollBody).toContain("Frag Arslan einfach noch einmal danach, wann immer du willst.");
    expect(de.kit.expiredConnectBody).toContain("Frag Arslan einfach noch einmal danach, wann immer du willst.");
  });

  it.each(LANGS)("%s: the Desktop lede says a scheduled task never waits for an answer, after the cards that wait in the window", (lang) => {
    const lede = LOCALES[lang].settings.desktopLede;
    expect(lede).toMatch(SCHEDULED_NEVER_WAITS[lang]);
    expect(lede.search(SCHEDULED_NEVER_WAITS[lang])).toBeGreaterThan(lede.search(NOT_A_NO[lang]));
    expect(lede).toMatch(/\b30\b/);                                                    // and the 30 minutes are still said
    expect(lede).toMatch(NOT_A_NO[lang]);
  });
});
