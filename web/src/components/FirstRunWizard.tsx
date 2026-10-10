/**
 * FirstRunWizard — the first-run film (0.1.60, docs/specs/2026-10-11-0160-first-run.md), shown once
 * when no model is configured yet (lib/firstRun.firstRunShouldShow).
 *
 * One stage, one head — the island's own (IslandMascot, the mouth carries the mood) — and a camera:
 *
 *   hello    — light rises; six language pills switch the whole screen at once
 *   model    — OpenRouter in one click, "Later", or your own key (tested before it is saved)
 *   folders  — Desktop/Documents/Downloads or only ~/Arslan: an explicit choice, nothing preselected
 *   hands    — only when Hands is here and not yet allowed: macOS's prompt, then a live check
 *   you      — an optional name; Start sends the head to its place in the app
 *
 * (The iPhone shot waits for the iPhone app to be on the App Store.)
 * The × skips setup at any point; Esc does not. Finishing or skipping persists the seen flag.
 */

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { X, Check, ArrowRight, ArrowUpRight, Folder, FolderLock, ChevronRight } from "lucide-react";
import type { ProviderOption, ProviderConfig } from "../api/client.types";
import {
  addProviderConfig,
  api,
  getOpenRouterOauthStatus,
  listProviderConfigs,
  startOpenRouterOauth,
  testLlm,
} from "../api/client";
import { openExternal } from "../lib/shell";
import { LANGUAGE_OPTIONS, normalizeLanguage } from "../lib/languages";
import { setFirstRunSeen, recordFirstTasks } from "../lib/firstRun";
import { useProfileStore } from "../stores/profileStore";
import { getHands, askHandsPermission, checkHands } from "./settings/HandsSection";
import IslandMascot from "../island/IslandMascot";
import type { Mood } from "../island/islandMachine";
import "../island/mascot.css";
import "./firstRun.css";
import { useLayer } from "./kit";

interface FirstRunWizardProps {
  llmProviders: ProviderOption[];
  /** Called with the newly created config so the parent can append it. */
  onAdded: (config: ProviderConfig) => void;
  /** Called after the wizard closes (finish or dismiss) so the parent hides it. */
  onClose: () => void;
  /** Keep the host's settings aligned even when the wizard is dismissed mid-save. */
  onLanguageChange?: (language: string) => void;
}

type Shot = "hello" | "model" | "folders" | "hands" | "you";
type Folders = "wide" | "own";

/** Where the head stands in each shot: centre as a fraction of the stage, and its scale. */
const CAMERA: Record<Shot, [number, number, number]> = {
  hello: [0.665, 0.49, 1],
  model: [0.705, 0.48, 0.86],
  folders: [0.69, 0.51, 1.12],
  hands: [0.71, 0.49, 0.94],
  you: [0.665, 0.49, 1],
};
/** How long the head takes to travel into the app on Start (matches .fr2-leaving in firstRun.css). */
export const HANDOFF_MS = 1300;
const HANDS_POLL_MS = 2000;
const HANDS_POLL_LIMIT = 90;   // three minutes of looking for the switch
const SETTLE_MS = 1100;        // a moment on the smile before the next shot

const reducedMotion = () =>
  typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function useDarkTheme(): boolean {
  const read = () => document.documentElement.classList.contains("dark");
  const [dark, setDark] = useState(read);
  useEffect(() => {
    const observer = new MutationObserver(() => setDark(read()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return dark;
}

function useStageSize(): { w: number; h: number } {
  const read = () => ({ w: window.innerWidth || 1280, h: window.innerHeight || 800 });
  const [size, setSize] = useState(read);
  useEffect(() => {
    const onResize = () => setSize(read());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return size;
}

export default function FirstRunWizard({ llmProviders, onAdded, onClose, onLanguageChange }: FirstRunWizardProps) {
  const { t, i18n } = useTranslation();
  const dark = useDarkTheme();
  const stage = useStageSize();
  const [shot, setShot] = useState<Shot>("hello");
  const [lit, setLit] = useState(false);
  const timers = useRef<number[]>([]);
  const later = (ms: number, fn: () => void) => { timers.current.push(window.setTimeout(fn, ms)); };
  useEffect(() => {
    later(reducedMotion() ? 0 : 250, () => setLit(true));
    const pending = timers.current;
    return () => { pending.forEach(clearTimeout); };
  }, []);

  // ── hello: language ──
  // normalize: the detector can report region-tagged codes ("en-US") that would
  // never match an option, leaving no language visibly selected.
  const [language, setLanguage] = useState<string>(normalizeLanguage(i18n.language));
  const pickLanguage = (code: string) => {
    setLanguage(code);
    i18n.changeLanguage(code);
    onLanguageChange?.(code);
    // Best-effort persist to backend settings so the choice survives a reload.
    api.updateSettings({ language: code }).catch(() => {});
  };

  // ── Hands: shown only when Hands is here and not yet allowed ──
  const [handsNeeded, setHandsNeeded] = useState<boolean | null>(null);
  const [handsPhase, setHandsPhase] = useState<"idle" | "waiting" | "allowed">("idle");
  const [handsOn, setHandsOn] = useState(false);
  useEffect(() => {
    let alive = true;
    Promise.resolve().then(() => getHands())
      .then((s) => { if (alive) { setHandsNeeded(Boolean(s?.available) && s.accessibility !== true); setHandsOn(s?.accessibility === true); } })
      .catch(() => { if (alive) setHandsNeeded(false); });
    return () => { alive = false; };
  }, []);

  // A ref too: `advance` also runs from timers set in an earlier render.
  const handsNeededRef = useRef<boolean | null>(null);
  handsNeededRef.current = handsNeeded;
  const shots: Shot[] = ["hello", "model", "folders", ...(handsNeeded ? ["hands" as const] : []), "you"];
  const advance = () => setShot((cur) => {
    const list: Shot[] = ["hello", "model", "folders", ...(handsNeededRef.current ? ["hands" as const] : []), "you"];
    const i = list.indexOf(cur);
    return i >= 0 && i < list.length - 1 ? list[i + 1] : cur;
  });

  // ── model ──
  const [provider, setProvider] = useState<string>(llmProviders[0]?.key ?? "");
  const [apiKey, setApiKey] = useState("");
  const [keyOpen, setKeyOpen] = useState(false);
  const [keyState, setKeyState] = useState<"idle" | "testing" | "ok" | "failed" | "saving">("idle");
  const [keyError, setKeyError] = useState("");
  const [orState, setOrState] = useState<"idle" | "waiting" | "connected" | "error" | "paid-fallback">("idle");
  const [orError, setOrError] = useState("");

  const connected = () => {
    setOrState("connected");
    later(reducedMotion() ? 0 : SETTLE_MS, advance);
  };

  /** Persist the key config (shared by the tested and the save-anyway paths). */
  const saveKey = async (): Promise<void> => {
    const info = llmProviders.find((p) => p.key === provider);
    const key = apiKey.trim();
    if (!info || !key) return;
    setKeyState("saving");
    try {
      const cfg = await addProviderConfig({
        label: info.label,
        provider: info.key,
        model: info.default_model,
        base_url: info.base_url,
        api_key: key,
      });
      onAdded(cfg);
    } catch {
      /* best-effort — user can still add a key later in Settings */
    }
    setKeyState("ok");
    connected();
  };

  /** Test first, save only on success — a bad key gets the REAL error plus an
   * explicit "save anyway" escape, instead of a silent blind save. */
  const testAndSave = async () => {
    const info = llmProviders.find((p) => p.key === provider);
    const key = apiKey.trim();
    if (!info || !key) return;
    setKeyState("testing");
    setKeyError("");
    try {
      const res = await testLlm({ provider: info.key, model: info.default_model, base_url: info.base_url, api_key: key });
      if (res.ok) {
        await saveKey();
      } else {
        setKeyState("failed");
        setKeyError(res.error || t("firstRun.testFailedGeneric"));
      }
    } catch (e) {
      setKeyState("failed");
      setKeyError(e instanceof Error ? e.message : String(e));
    }
  };

  async function signInWithOpenRouter() {
    setOrState("waiting");
    setOrError("");
    try {
      const { auth_url } = await startOpenRouterOauth();
      // The URL's one legal path: backend → response → the shell doorway.
      await openExternal(auth_url);
      for (let i = 0; i < 90; i++) {
        const st = await getOpenRouterOauthStatus();
        if (st.state === "done") {
          const configs = await listProviderConfigs();
          const created = configs.find((c) => c.id === st.config_id);
          if (created) onAdded(created);
          if (st.free_model === false) {
            // The fallback is STATED: the default model may need credit, and the
            // zero-card user this button exists for must hear that from us, not
            // from a 402.
            setOrState("paid-fallback");
            return;
          }
          connected();
          return;
        }
        if (st.state === "error") {
          setOrState("error");
          setOrError(st.error || "authorization failed");
          return;
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
      setOrState("error");
      setOrError("authorization timed out — the browser tab may still be waiting");
    } catch (e) {
      setOrState("error");
      setOrError(e instanceof Error ? e.message : String(e));
    }
  }

  // ── folders: an explicit choice ──
  const [folders, setFolders] = useState<Folders | null>(null);
  const pickFolders = (choice: Folders) => {
    if (folders) return;
    setFolders(choice);
    api.updateSettings({ default_read_enabled: choice === "wide" ? "true" : "false" }).catch(() => {});
    later(reducedMotion() ? 0 : SETTLE_MS, advance);
  };

  // ── Hands ──
  const allowHands = async () => {
    setHandsPhase("waiting");
    try {
      const asked = await askHandsPermission("accessibility");
      if (asked?.accessibility === true) return handsAllowed();
    } catch {
      /* the check below still finds the switch */
    }
    for (let i = 0; i < HANDS_POLL_LIMIT; i++) {
      await new Promise((r) => setTimeout(r, HANDS_POLL_MS));
      try {
        const st = await checkHands();
        if (st?.accessibility === true) return handsAllowed();
      } catch {
        /* keep looking */
      }
    }
  };
  const handsAllowed = () => {
    setHandsPhase("allowed");
    setHandsOn(true);
    later(reducedMotion() ? 0 : SETTLE_MS, advance);
  };

  // ── you ──
  const setDisplayName = useProfileStore((s) => s.setDisplayName);
  const [name, setName] = useState("");
  const [leaving, setLeaving] = useState<{ x: number; y: number; s: number } | null>(null);

  const finish = () => {
    setFirstRunSeen();
    onClose();
  };
  const dismiss = () => {
    setFirstRunSeen();
    onClose();
  };
  const start = () => {
    const trimmed = name.trim();
    if (trimmed) setDisplayName(trimmed);
    recordFirstTasks({ folders: folders === "wide", hands: handsOn });
    // The head travels to its place in the app: the empty conversation's mark, measured live.
    const anchor = document.querySelector("[data-brand-anchor]") as HTMLElement | null;
    const box = anchor?.getBoundingClientRect();
    if (reducedMotion() || !box || box.width === 0) {
      finish();
      return;
    }
    setLeaving({ x: box.left + box.width / 2, y: box.top + box.height / 2, s: box.width / headSize });
    later(HANDOFF_MS, finish);
  };

  // 0.1.55: the top layer while it is shown, so no card underneath answers to keys.
  // Deliberately NOT closed by Esc: skipping setup is a choice made with the ×.
  useLayer(true);

  // ── the camera ──
  const narrow = stage.w < 980;
  const headSize = Math.round(Math.max(260, Math.min(520, stage.h * 0.55)));
  const [cx, cy, cs] = narrow ? [0.5, 0.24, 0.62] : CAMERA[shot];
  const cam = leaving
    ? { x: leaving.x, y: leaving.y, s: leaving.s }
    : { x: stage.w * cx, y: stage.h * cy, s: cs };
  const mood: Mood =
    shot === "model" ? (orState === "waiting" ? "working" : orState === "connected" ? "finished" : "idle")
      : shot === "folders" ? (folders ? "finished" : "approval")
        : shot === "hands" ? (handsPhase === "allowed" ? "finished" : "approval")
          : shot === "you" ? "finished" : "idle";
  const step = shots.indexOf(shot) + 1;
  const eyebrow = (label: string) => `${String(step).padStart(2, "0")} — ${t(label)}`;
  const busy = keyState === "testing" || keyState === "saving";

  return (
    <div className={`fr2 ${dark ? "fr2-dark" : "fr2-light"}${lit ? " fr2-lit" : ""}${leaving ? " fr2-leaving" : ""}${narrow ? " fr2-narrow" : ""}`}
      role="dialog" aria-modal="true" aria-labelledby="first-run-title" data-testid="first-run" data-shot={shot}>
      <div className="fr2-lamp" aria-hidden="true" />
      <div className="fr2-vignette" aria-hidden="true" />
      <svg className="fr2-grain" aria-hidden="true" width="100%" height="100%">
        <filter id="fr2-grain"><feTurbulence type="fractalNoise" baseFrequency=".85" numOctaves={2} stitchTiles="stitch" /><feColorMatrix type="saturate" values="0" /></filter>
        <rect width="100%" height="100%" filter="url(#fr2-grain)" />
      </svg>

      <div className="fr2-head" data-testid="first-run-head" data-mood={mood}
        style={{ width: headSize, height: headSize, transform: `translate(${cam.x - headSize / 2}px, ${cam.y - headSize / 2}px) scale(${cam.s})` }}>
        <IslandMascot mood={mood} size={headSize} tone={dark ? "paper" : "ink"} />
      </div>

      <button type="button" data-testid="first-run-dismiss" onClick={dismiss} className="fr2-x"
        title={t("firstRun.skip")} aria-label={t("firstRun.skip")}>
        <X className="w-4 h-4" />
      </button>

      <div className="fr2-bars" role="img" aria-label={`${step} / ${shots.length}`}>
        {shots.map((s, i) => <span key={s} className={i < step ? "on" : ""} />)}
      </div>

      {/* keyed by shot so the text cross-fades in as the camera moves */}
      <div className="fr2-panel" key={shot}>
        {shot === "hello" && (
          <>
            <p className="fr2-eyebrow">{eyebrow("firstRun.eyebrowHello")}</p>
            <h1 id="first-run-title" className="fr2-title">{t("firstRun.helloTitle")}</h1>
            <p className="fr2-body">{t("firstRun.helloBody")}</p>
            <div className="fr2-langs" role="group" aria-label={t("firstRun.languageLabel")}>
              {LANGUAGE_OPTIONS.map((o) => (
                <button key={o.code} type="button" data-testid={`first-run-lang-${o.code}`} aria-pressed={language === o.code}
                  onClick={() => pickLanguage(o.code)} className={`fr2-pill${language === o.code ? " on" : ""}`}>
                  {o.label}
                </button>
              ))}
            </div>
            <div className="fr2-actions">
              <button type="button" data-testid="first-run-next" onClick={advance} className="fr2-pri">
                {t("firstRun.begin")}<ArrowRight className="w-4 h-4" aria-hidden="true" />
              </button>
            </div>
          </>
        )}

        {shot === "model" && (
          <>
            <p className="fr2-eyebrow">{eyebrow("firstRun.eyebrowModel")}</p>
            <h1 id="first-run-title" className="fr2-title">{t("firstRun.modelTitle")}</h1>
            <p className="fr2-body">{t("firstRun.modelBody")}</p>
            {orState === "waiting" ? (
              <p className="fr2-status" role="status"><span className="fr2-dot fr2-dot-blue" aria-hidden="true" />{t("firstRun.openrouterWaiting")}</p>
            ) : orState === "connected" ? (
              <p className="fr2-status" role="status"><Check className="w-4 h-4 fr2-ok" aria-hidden="true" />
                {keyState === "ok" ? t("firstRun.testOk") : t("firstRun.openrouterConnected")}</p>
            ) : orState === "paid-fallback" ? (
              <>
                <p className="fr2-note fr2-warn" role="status">{t("firstRun.openrouterPaidFallback")}</p>
                <div className="fr2-actions">
                  <button type="button" data-testid="first-run-continue" onClick={advance} className="fr2-pri">
                    {t("firstRun.continue")}<ArrowRight className="w-4 h-4" aria-hidden="true" />
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="fr2-actions">
                  <button type="button" data-testid="openrouter-signin" onClick={() => void signInWithOpenRouter()} className="fr2-pri">
                    {t("firstRun.openrouterContinue")}<ArrowUpRight className="w-4 h-4" aria-hidden="true" />
                  </button>
                  <button type="button" data-testid="first-run-add-later" onClick={advance} className="fr2-ghost">
                    {t("firstRun.later")}
                  </button>
                </div>
                {orState === "error" && <p className="fr2-note fr2-err" role="alert">{orError}</p>}
                <button type="button" data-testid="first-run-own-key" aria-expanded={keyOpen}
                  onClick={() => setKeyOpen((v) => !v)} className={`fr2-fold${keyOpen ? " open" : ""}`}>
                  {t("firstRun.ownKey")}<ChevronRight className="w-3.5 h-3.5" aria-hidden="true" />
                </button>
                {keyOpen && (
                  <div className="fr2-keyform">
                    <label className="fr2-label">{t("firstRun.providerLabel")}
                      <select data-testid="first-run-provider" value={provider} className="fr2-field"
                        onChange={(e) => { setProvider(e.target.value); setKeyState("idle"); setKeyError(""); }}>
                        {llmProviders.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
                      </select>
                    </label>
                    <label className="fr2-label">{t("firstRun.keyLabel")}
                      <input data-testid="first-run-key" type="password" value={apiKey} className="fr2-field"
                        placeholder={t("firstRun.keyPlaceholder")}
                        onChange={(e) => { setApiKey(e.target.value); if (keyState === "failed") { setKeyState("idle"); setKeyError(""); } }} />
                    </label>
                    <p className="fr2-note fr2-wide">{t("firstRun.keyNote")}</p>
                    <div className="fr2-wide fr2-keyrow">
                      <button type="button" data-testid="first-run-test-save" disabled={busy || !apiKey.trim()}
                        onClick={() => void testAndSave()} className="fr2-ghost fr2-small">
                        {keyState === "testing" ? t("firstRun.testing") : t("firstRun.testSave")}
                      </button>
                      {keyState === "failed" && (
                        <button type="button" data-testid="first-run-save-anyway" onClick={() => void saveKey()} className="fr2-link">
                          {t("firstRun.saveAnyway")}
                        </button>
                      )}
                    </div>
                    {keyState === "failed" && <p className="fr2-note fr2-err fr2-wide" role="alert">{keyError}</p>}
                  </div>
                )}
              </>
            )}
          </>
        )}

        {shot === "folders" && (
          <>
            <p className="fr2-eyebrow">{eyebrow("firstRun.eyebrowFolders")}</p>
            <h1 id="first-run-title" className="fr2-title">{t("firstRun.foldersTitle")}</h1>
            <p className="fr2-body">{t("firstRun.foldersBody")}</p>
            <div className="fr2-cards" role="group" aria-label={t("firstRun.foldersTitle")}>
              {([["wide", Folder], ["own", FolderLock]] as const).map(([key, Icon]) => (
                <button key={key} type="button" data-testid={`first-run-folders-${key}`} aria-pressed={folders === key}
                  disabled={folders !== null && folders !== key} onClick={() => pickFolders(key)}
                  className={`fr2-card${folders === key ? " on" : ""}`}>
                  <Icon className="w-6 h-6" aria-hidden="true" strokeWidth={1.5} />
                  <span className="fr2-card-title">{t(key === "wide" ? "firstRun.foldersWide" : "firstRun.foldersOwn")}</span>
                  <span className="fr2-card-body">{t(key === "wide" ? "firstRun.foldersWideBody" : "firstRun.foldersOwnBody")}</span>
                  {folders === key && <span className="fr2-card-check" aria-hidden="true"><Check className="w-3.5 h-3.5" /></span>}
                </button>
              ))}
            </div>
          </>
        )}

        {shot === "hands" && (
          <>
            <p className="fr2-eyebrow">{eyebrow("firstRun.eyebrowHands")}</p>
            <h1 id="first-run-title" className="fr2-title">{t("firstRun.handsTitle")}</h1>
            <p className="fr2-body">{t("firstRun.handsBody")}</p>
            <div className="fr2-actions">
              <button type="button" data-testid="first-run-hands-open" disabled={handsPhase !== "idle"}
                onClick={() => void allowHands()} className="fr2-pri">
                {t("firstRun.handsOpen")}<ArrowUpRight className="w-4 h-4" aria-hidden="true" />
              </button>
              <button type="button" data-testid="first-run-hands-skip" onClick={advance} className="fr2-ghost">
                {t("firstRun.notNow")}
              </button>
            </div>
            <p className={`fr2-status${handsPhase === "idle" ? " fr2-muted" : ""}`} role="status" data-testid="first-run-hands-status">
              {handsPhase === "allowed"
                ? <Check className="w-4 h-4 fr2-ok" aria-hidden="true" />
                : <span className={`fr2-dot${handsPhase === "waiting" ? " fr2-dot-amber" : ""}`} aria-hidden="true" />}
              {t(handsPhase === "allowed" ? "firstRun.handsAllowed" : handsPhase === "waiting" ? "firstRun.handsWaiting" : "firstRun.handsIdle")}
            </p>
          </>
        )}

        {shot === "you" && (
          <>
            <p className="fr2-eyebrow">{eyebrow("firstRun.eyebrowYou")}</p>
            <h1 id="first-run-title" className="fr2-title">{t("firstRun.youTitle")}</h1>
            <p className="fr2-body">{t("firstRun.youBody")}</p>
            <label className="fr2-label fr2-name">{t("firstRun.nameLabel")}
              <input data-testid="first-run-name" type="text" value={name} autoComplete="given-name" className="fr2-field"
                placeholder={t("firstRun.namePlaceholder")} onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") start(); }} />
            </label>
            <div className="fr2-actions">
              <button type="button" data-testid="first-run-finish" onClick={start} disabled={Boolean(leaving)} className="fr2-pri">
                {t("firstRun.start")}<ArrowRight className="w-4 h-4" aria-hidden="true" />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
