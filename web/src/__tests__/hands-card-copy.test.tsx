/** 0.1.61 §A11 (PR 2b Task 7): the words on the cards ③Hands asks with, in all six languages.
 *
 *  ③Hands moved onto `permissions.decide`. Looking at an app and acting in it is ONE `desktop_app` card now (there is no
 *  `desktop_look` card any more: the server's looks ask with `desktop_app`, tests/server/test_hands_0153.py), so its title and
 *  its grant line must say it covers both, and the old "Asked once per app in this conversation" is gone: a card of the
 *  task-first kinds (app, site, Shortcut) is answered "for this task" first, with "in this conversation" the wider choice.
 *  A takeover card is answered in Arslan, never from the island. */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import ActionApprovalCard from "../components/ActionApprovalCard";
import IslandApp from "../island/IslandApp";
import { handsMessages } from "../locales/hands";
import { MESSAGES, t as islandText } from "../locales/island";
import type { PendingCard } from "../island/feed";

const LANGS = ["en", "zh", "ja", "es", "de", "fr"] as const;
type Lang = (typeof LANGS)[number];
const per = <T,>(v: Record<Lang, T>) => v;

// What each language's words for the thing are. `Record<Lang, …>` so a missing language is a type error.
const LOOK_IN_TITLE = per<RegExp>({ en: /look at/i, zh: /查看/, ja: /見て/, es: /mirar/i, de: /ansehen/i, fr: /regarder/i });
const ACT_IN_TITLE = per<RegExp>({ en: /act in/i, zh: /操作/, ja: /操作/, es: /actuar/i, de: /handeln/i, fr: /agir/i });
const LOOK_IN_LINE = per<RegExp>({ en: /looking at this app's window/i, zh: /查看这个 App 的窗口/, ja: /ウインドウを見ること/, es: /mirar la ventana/i,
  de: /Fenster dieser App anzusehen/, fr: /regarder la fenêtre/i });
const ACT_IN_LINE = per<RegExp>({ en: /clicking, typing and choosing/i, zh: /点击、输入和选择/, ja: /クリック・入力・選択/, es: /hacer clic, escribir y elegir/i,
  de: /klicken, zu tippen und auszuwählen/, fr: /cliquer, saisir et choisir/i });
const TASK = per<RegExp>({ en: /this task/i, zh: /本次任务内/, ja: /このタスクの間/, es: /esta tarea/i, de: /diese Aufgabe/, fr: /cette tâche/i });
const PIECE_OF_WORK = per<RegExp>({ en: /piece of work/i, zh: /这件事/, ja: /この作業/, es: /este trabajo/i, de: /diese Arbeit/, fr: /ce travail/i });
const ONCE_PER_APP = per<RegExp>({
  en: /once per app/i, zh: /每个 ?App 只问一次|每个应用在每个对话里问一次|每件事每个应用问一次/, ja: /アプリごとに一度/,
  es: /una vez por app/i, de: /einmal pro App/i, fr: /une fois par app/i });
/** The old Settings › Hands sentence: looking and acting asked apart. */
const ASKED_APART = per<RegExp>({ en: /Looking asks|acting asks/, zh: /查看时每个应用|动手时每件事/, ja: /見るときは会話ごと/, es: /Mirar pregunta|actuar pregunta/,
  de: /Ansehen fragt|Handeln fragt/, fr: /Regarder demande|agir demande/ });
const ONE_CARD = per<RegExp>({ en: /One card covers looking at an app and acting in it/, zh: /查看和操作一个应用只问一张卡/, ja: /1 枚のカードで確認し/,
  es: /Una sola tarjeta cubre mirar una app y actuar en ella/, de: /Eine einzige Karte deckt Ansehen und Handeln/, fr: /Une seule carte couvre regarder une app et y agir/ });

const flat = (o: unknown): string[] => (typeof o === "string" ? [o] : o && typeof o === "object" ? Object.values(o).flatMap(flat) : []);

describe("there is no desktop_look card any more", () => {
  // Nothing asks with it: a look asks with `desktop_app` (the server's tests pin the kind of every card a look shows), so the
  // card keeps no words for it. A stray frame of that kind reads as a kind this card has no words for: the frame's own question.
  it.each(LANGS)("%s: no desktop_look title, scope or grant on the card, none in the island's names for a card", (lang) => {
    for (const part of [handsMessages[lang].title, handsMessages[lang].scope, handsMessages[lang].grant]) expect(part).not.toHaveProperty("desktop_look");
    expect(MESSAGES[lang].ask).not.toHaveProperty("desktop_look");
  });

  it("a stray frame of the old kind is a kind it has no words for: the frame's own question, never a missing-key name", () => {
    render(<ActionApprovalCard kind="desktop_look" target="Notes" detail="" title="Read Notes?" options={["task", "conversation"]}
      onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId("action-title")).toHaveTextContent("Read Notes?");
    expect(screen.getByTestId("action-card").textContent).not.toMatch(/hands\./);
    expect(screen.queryByText(/hands\.(title|scope|grant)\.desktop_look/)).toBeNull();
  });
});

describe("one desktop_app card covers looking AND acting", () => {
  it.each(LANGS)("%s: the title says both, and so do the grant and scope lines", (lang) => {
    const m = handsMessages[lang];
    expect(m.title.desktop_app, `${lang} title`).toMatch(LOOK_IN_TITLE[lang]);
    expect(m.title.desktop_app, `${lang} title`).toMatch(ACT_IN_TITLE[lang]);
    expect(m.title.desktop_app, `${lang} title`).toContain("{{target}}");
    for (const line of [m.grant.desktop_app, m.scope.desktop_app]) {
      expect(line, `${lang} line`).toMatch(LOOK_IN_LINE[lang]);
      expect(line, `${lang} line`).toMatch(ACT_IN_LINE[lang]);
    }
  });

  it.each(LANGS)("%s: the island names the card the same way", (lang) => {
    const named = (MESSAGES[lang].ask as Record<string, string>).desktop_app;
    expect(named).toMatch(LOOK_IN_TITLE[lang]);
    expect(named).toMatch(ACT_IN_TITLE[lang]);
  });

  it.each(LANGS)("%s: rendered, the card reads as both, task first, with the grant under it", async (lang) => {
    await i18n.changeLanguage(lang);
    render(<ActionApprovalCard kind="desktop_app" target="Notes" detail="Arslan wants to use Notes for this" permKind="app"
      options={["task", "conversation", "always"]} alwaysLabel="Notes" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    const title = screen.getByTestId("action-title").textContent ?? "";
    expect(title).toContain("Notes");
    expect(title).toMatch(LOOK_IN_TITLE[lang]);
    expect(title).toMatch(ACT_IN_TITLE[lang]);
    expect(screen.getByTestId("action-card")).toHaveTextContent(handsMessages[lang].grant.desktop_app);
    expect(screen.getByTestId("action-card").textContent).not.toContain(handsMessages[lang].scope.desktop_app);     // a choice is shown: no how-long sentence
    const choices = screen.getAllByRole("radio");
    expect(choices).toHaveLength(3);
    expect(choices[0]).toBeChecked();
    expect(choices[0].closest("label")).toHaveTextContent(String(i18n.t("kit.scope.task")));
    expect(choices[1].closest("label")).toHaveTextContent(String(i18n.t("kit.scope.conversation")));
  });

  it.each(LANGS)("%s: an app that reaches every other app offers task and conversation only, still task first", async (lang) => {
    await i18n.changeLanguage(lang);
    render(<ActionApprovalCard kind="desktop_app" target="Terminal" detail="" permKind="app" options={["task", "conversation"]}
      alwaysLabel="" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    const choices = screen.getAllByRole("radio");
    expect(choices).toHaveLength(2);
    expect(choices[0]).toBeChecked();
    expect(choices[0].closest("label")).toHaveTextContent(String(i18n.t("kit.scope.task")));
  });
});

describe("the task-first cards are task first in words", () => {
  const KINDS = ["desktop_app", "browser_site", "mac_shortcut"] as const;

  it.each(LANGS)("%s: the scope line of an app, a site and a Shortcut card says this task — not 'this piece of work' — and nothing is asked 'once per app'", (lang) => {
    for (const kind of KINDS) {
      const line = handsMessages[lang].scope[kind];
      expect(line, `${lang}.scope.${kind}`).toMatch(TASK[lang]);
      expect(line, `${lang}.scope.${kind}`).not.toMatch(PIECE_OF_WORK[lang]);
    }
    for (const line of flat(handsMessages[lang])) expect(line, `${lang}: ${line.slice(0, 40)}…`).not.toMatch(ONCE_PER_APP[lang]);
  });

  it("the guard itself: each language's old wording is caught by the patterns", () => {
    const olderOncePerApp: Record<Lang, string> = {
      en: "Asked once per app in this conversation.", zh: "本对话里每个 App 只问一次。", ja: "この会話ではアプリごとに一度だけ確認します。",
      es: "Se pregunta una vez por app en esta conversación.", de: "Einmal pro App in dieser Unterhaltung gefragt.", fr: "Demandé une fois par app dans cette conversation.",
    };
    const olderWork: Record<Lang, string> = {
      en: "for this piece of work only", zh: "只在这件事里允许", ja: "この作業の間だけ", es: "solo para este trabajo", de: "nur für diese Arbeit", fr: "pour ce travail uniquement",
    };
    for (const lang of LANGS) {
      expect(olderOncePerApp[lang], lang).toMatch(ONCE_PER_APP[lang]);
      expect(olderWork[lang], lang).toMatch(PIECE_OF_WORK[lang]);
      expect(olderWork[lang], lang).not.toMatch(TASK[lang]);
    }
  });

  it.each(LANGS)("%s: rendered, a site card is task first, and its grant stays under it", async (lang) => {
    await i18n.changeLanguage(lang);
    render(<ActionApprovalCard kind="browser_site" target="https://github.com" detail="click" permKind="site"
      options={["task", "conversation", "always"]} alwaysLabel="github.com" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    const choices = screen.getAllByRole("radio");
    expect(choices).toHaveLength(3);
    expect(choices[0]).toBeChecked();
    expect(choices[0].closest("label")).toHaveTextContent(String(i18n.t("kit.scope.task")));
    expect(screen.getByTestId("action-card")).toHaveTextContent(handsMessages[lang].grant.browser_site);
  });
});

describe("Settings › Hands says one card covers looking and acting", () => {
  it.each(LANGS)("%s: looking and acting are no longer 'asked apart'", (lang) => {
    const lede = handsMessages[lang].settings.lede;
    expect(lede).toMatch(ONE_CARD[lang]);
    expect(lede).not.toMatch(ASKED_APART[lang]);
    expect(lede).not.toMatch(ONCE_PER_APP[lang]);
  });
});

describe("a takeover card is answered in Arslan, never from the island", () => {
  const feed = { cursor: 3, awaiting: 1, awaiting_conversations: ["c1"], events: [], enabled: true, active: [] };
  // The card ③Hands asks with: kind desktop_takeover, perm_kind takeover, one choice. The server says island_ok false for it
  // (tests/server/test_island_approvals.py), and the island must not offer what the server refuses.
  const takeover: PendingCard = { call_id: "t1", conversation_id: "c1", opened_at: 1000, expires_at: 1300, island_ok: false,
    frame: { type: "propose_action", kind: "desktop_takeover", target: "5 min · tidy the desktop", perm_kind: "takeover", options: ["once"],
      title: "Take over the screen for about 5 minutes?", detail: "" } };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.startsWith("/api/v1/island/feed")) return new Response(JSON.stringify(feed), { status: 200 });
      if (url === "/api/v1/approvals/pending") return new Response(JSON.stringify([takeover]), { status: 200 });
      return new Response("{}", { status: 200 });
    }));
  });
  afterEach(async () => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); localStorage.clear(); await i18n.changeLanguage("en"); });

  it.each(LANGS)("%s: the island shows no Allow for it — only Decline and Open in Arslan", async (lang) => {
    localStorage.setItem("i18nextLng", lang);
    render(<IslandApp />);
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(screen.getByTestId("island-open-in-arslan")).toHaveTextContent(islandText(lang, "openInArslan"));
    expect(screen.queryByTestId("island-allow")).toBeNull();
    expect(screen.getByTestId("island-decline")).toHaveTextContent(islandText(lang, "decline"));
    expect(screen.getByTestId("island-ask-line")).toHaveTextContent("5 min · tidy the desktop");
    expect(document.body).toHaveTextContent((MESSAGES[lang].ask as Record<string, string>).desktop_takeover);   // it is named, not "Needs your OK"
  });
});

// ── Fix round 1 ────────────────────────────────────────────────────────────────────────────────────────────────

/** The title joins the two with "and" — a flipped "or" ("Mirar o actuar") keeps both keywords, so the conjunction itself is pinned. */
const LOOK_AND_ACT = per<RegExp>({ en: /Look at and act in/, zh: /查看并操作/, ja: /見て操作/, es: /Mirar y actuar en/, de: /ansehen und darin handeln/, fr: /Regarder et agir dans/ });
const SITE_ACTS = per<RegExp>({ en: /clicking, typing and choosing/, zh: /点击、输入和选择/, ja: /クリック・入力・選択/, es: /hacer clic, escribir y elegir/,
  de: /zu klicken, zu tippen und auszuwählen/, fr: /les clics, la saisie et les choix/ });
const SITE_READS = per<RegExp>({ en: /reading the page/, zh: /读取页面/, ja: /ページの読み取り/, es: /leer la página/, de: /die Seite zu lesen/, fr: /lecture de la page/ });

describe("fix round 1: the words that carry the meaning", () => {
  it.each(LANGS)("%s: the app title and the island's name for it join looking and acting with 'and'", (lang) => {
    expect(handsMessages[lang].title.desktop_app).toMatch(LOOK_AND_ACT[lang]);
    expect((MESSAGES[lang].ask as Record<string, string>).desktop_app).toMatch(per<RegExp>({
      en: /Look at and act in/, zh: /查看并操作/, ja: /見て操作/, es: /Mirar y actuar en/, de: /ansehen und darin handeln/, fr: /Regarder et agir dans/ })[lang]);
  });

  it.each(LANGS)("%s: a site card's grant and scope say what the server grants: reading the page, clicking, typing and choosing", (lang) => {
    for (const line of [handsMessages[lang].grant.browser_site, handsMessages[lang].scope.browser_site]) {
      expect(line, lang).toMatch(SITE_READS[lang]);
      expect(line, lang).toMatch(SITE_ACTS[lang]);
    }
  });

  it("German calls the buttons 'Schaltflächen' (not 'Tasten', which are keys); French types nothing into a password field, as the site card says", () => {
    for (const line of [handsMessages.de.grant.desktop_app, handsMessages.de.scope.desktop_app]) {
      expect(line).toMatch(/Schaltflächen/);
      expect(line).not.toMatch(/Text, Tasten/);
    }
    for (const line of [handsMessages.fr.grant.desktop_app, handsMessages.fr.scope.desktop_app]) {
      expect(line).toContain("ne saisit jamais de mot de passe");
      expect(line).not.toMatch(/ne tape jamais/);
    }
  });

  it("the guard itself: the two patterns catch the wording they replace", () => {
    expect("Mirar o actuar en Notes").not.toMatch(LOOK_AND_ACT.es);
    expect("Allows clicking and typing on this website for this task only.").not.toMatch(SITE_READS.en);
  });
});

describe("fix round 1: a stray frame of the kind that is gone (a pre-0.1.61 desktop_look) is still a card with a label", () => {
  // A pre-0.1.61 frame has no title, no choices, no permission kind and an empty detail. It must render something readable and be answerable.
  const stray = { type: "propose_action", kind: "desktop_look", target: "Notes", detail: "" };

  it.each(LANGS)("%s: on the island it is named 'Needs your OK' with the app under it, and can be declined", async (lang) => {
    vi.useFakeTimers();
    localStorage.setItem("i18nextLng", lang);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.startsWith("/api/v1/island/feed")) return new Response(JSON.stringify({ cursor: 3, awaiting: 1, awaiting_conversations: ["c1"], events: [], enabled: true, active: [] }), { status: 200 });
      if (url === "/api/v1/approvals/pending") return new Response(JSON.stringify([{ call_id: "s1", conversation_id: "c1", opened_at: 1000, expires_at: 1300, island_ok: false, frame: stray }]), { status: 200 });
      return new Response("{}", { status: 200 });
    }));
    try {
      render(<IslandApp />);
      await act(async () => { await vi.advanceTimersByTimeAsync(600); });
      expect(document.body).toHaveTextContent((MESSAGES[lang].ask as Record<string, string>).other);
      expect(screen.getByTestId("island-ask-line")).toHaveTextContent("Notes");
      expect(screen.getByTestId("island-decline")).toBeInTheDocument();
      expect(screen.getByTestId("island-risky")).toHaveTextContent(islandText(lang, "heldGeneric"));       // a kind it does not know: the neutral line
    } finally {
      cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); localStorage.clear();
    }
  });

  it("in the conversation it is a card headed by the app, with Allow and No (the Inbox's copy went with the Inbox, INB5b-2)", async () => {
    const { default: AskSlot } = await import("../components/AskSlot");
    const { useArslanStore, initialArslanState } = await import("../stores/arslanStore");
    useArslanStore.setState(initialArslanState(), true);
    try {
      act(() => { useArslanStore.getState().handleFrame({ ...stray, call_id: "s1" } as never); });
      render(<AskSlot send={() => {}} />);
      const card = screen.getByTestId("action-card");
      expect(screen.getByTestId("action-title")).toHaveTextContent("Notes");
      expect(card.textContent?.trim()).not.toBe("");
      expect(screen.getByTestId("action-allow")).toBeInTheDocument();
      expect(screen.getByTestId("action-deny")).toBeInTheDocument();
    } finally {
      cleanup(); useArslanStore.setState(initialArslanState(), true);
    }
  });
});
