/**
 * FirstRunWizard — the first-touch onboarding overlay, shown once when no
 * provider/model is configured yet (see lib/firstRun.firstRunShouldShow).
 *
 * Four steps over a looping character video, content on a frosted-glass panel
 * (all visual styling lives in firstRun.css — this file stays token/color-free):
 *
 *   1. language   — FIRST, so every later step renders in the chosen language
 *   2. how it works — four-beat product tour
 *   3. connect a model — OpenRouter one-click sign-in OR a BYOK key that is
 *      TESTED (POST /settings/test-llm) before it is saved; a failing key shows
 *      the real error and offers "save anyway" instead of saving blind
 *   4. hello — welcome copy + an optional name / one-line intro, stored in the
 *      same profileStore field Settings edits, so Arslan greets by name
 *
 * Dismissible at any point; on finish OR dismiss it persists the firstRunSeen
 * flag so it never nags again.
 */

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { X, Check } from "lucide-react";
import type { CatalogEntry, ProviderOption, ProviderConfig } from "../api/client.types";
import {
  addProviderConfig,
  api,
  getCatalog,
  getOpenRouterOauthStatus,
  listProviderConfigs,
  startOpenRouterOauth,
  testLlm,
} from "../api/client";
import { openExternal } from "../lib/shell";
import { LANGUAGE_OPTIONS, normalizeLanguage } from "../lib/languages";
import { setFirstRunSeen } from "../lib/firstRun";
import { useProfileStore } from "../stores/profileStore";
import "./firstRun.css";

interface FirstRunWizardProps {
  llmProviders: ProviderOption[];
  /** Called with the newly created config so the parent can append it. */
  onAdded: (config: ProviderConfig) => void;
  /** Called after the wizard closes (finish or dismiss) so the parent hides it. */
  onClose: () => void;
}

const TOTAL_STEPS = 4;
const STEP_LANG = 0;
const STEP_HOW = 1;
const STEP_KEY = 2;
const STEP_HELLO = 3;

export default function FirstRunWizard({ llmProviders, onAdded, onClose }: FirstRunWizardProps) {
  const { t, i18n } = useTranslation();
  const [step, setStep] = useState(STEP_LANG);
  const [bgMissing, setBgMissing] = useState(false);

  // ── step 1: language ──
  // normalize: the detector can report region-tagged codes ("en-US") that would
  // never match an option, leaving no language visibly selected.
  const [language, setLanguage] = useState<string>(normalizeLanguage(i18n.language));

  const pickLanguage = (code: string) => {
    setLanguage(code);
    i18n.changeLanguage(code);
    // Best-effort persist to backend settings so the choice survives a reload.
    api.updateSettings({ language: code }).catch(() => {});
  };

  // ── step 3: connect a model ──
  const [provider, setProvider] = useState<string>(llmProviders[0]?.key ?? "");
  const [apiKey, setApiKey] = useState("");
  const [keyState, setKeyState] = useState<"idle" | "testing" | "ok" | "failed" | "saving">("idle");
  const [keyError, setKeyError] = useState("");
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [orState, setOrState] = useState<"idle" | "waiting" | "error" | "paid-fallback">("idle");
  const [orError, setOrError] = useState("");

  // Capability annotation for the selected provider, straight from the server's
  // read-only catalog (arslan/llm/catalog.py) — never hardcoded per provider.
  useEffect(() => {
    getCatalog().then(setCatalog).catch(() => {});
  }, []);
  const capabilities = catalog.find((c) => c.provider === provider)?.capabilities;

  // ── step 4: hello ──
  const setDisplayName = useProfileStore((s) => s.setDisplayName);
  const [name, setName] = useState("");

  const finish = () => {
    setFirstRunSeen();
    onClose();
  };

  const dismiss = () => {
    setFirstRunSeen();
    onClose();
  };

  const finishHello = () => {
    const trimmed = name.trim();
    if (trimmed) setDisplayName(trimmed);
    finish();
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
    setStep(STEP_HELLO);
  };

  /** Test first, save only on success — a bad key gets the REAL error plus an
   * explicit "save anyway" escape, instead of the old silent blind save. */
  const testAndSave = async () => {
    const info = llmProviders.find((p) => p.key === provider);
    const key = apiKey.trim();
    if (!info || !key) return;
    setKeyState("testing");
    setKeyError("");
    try {
      const res = await testLlm({
        provider: info.key,
        model: info.default_model,
        base_url: info.base_url,
        api_key: key,
      });
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
          setOrState("idle");
          setStep(STEP_HELLO);
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

  const busy = keyState === "testing" || keyState === "saving";

  return (
    <div className="fr-root animate-fade-in">
      {/* The video is the aesthetic — the frosted panel only reads as glass with
          content moving behind it. On error (asset missing, or a webview without
          h264) the poster-frame fallback stands in so the wizard still works. */}
      {!bgMissing ? (
        <video
          className="fr-bg"
          src="/first-run/bg.mp4"
          poster="/first-run/poster.jpg"
          autoPlay
          muted
          loop
          playsInline
          onError={() => setBgMissing(true)}
        />
      ) : (
        <div className="fr-bg fr-bg-fallback" />
      )}
      <div className="fr-shade" />

      <div className="fr-glass">
        <button
          type="button"
          data-testid="first-run-dismiss"
          onClick={dismiss}
          className="fr-x"
          title={t("firstRun.skip")}
        >
          <X className="w-4 h-4" />
        </button>

        {/* body — keyed by step so the 220ms crossfade replays on each change */}
        <div className="fr-step" key={step}>
          {step === STEP_LANG && (
            <>
              <h2 className="fr-h1">{t("firstRun.stepLanguage")}</h2>
              <p className="fr-sub">{t("firstRun.stepLanguageHint")}</p>
              <div className="fr-langs">
                {LANGUAGE_OPTIONS.map((o) => (
                  <button
                    key={o.code}
                    type="button"
                    data-testid={`first-run-lang-${o.code}`}
                    onClick={() => pickLanguage(o.code)}
                    className={`fr-lang${language === o.code ? " on" : ""}`}
                  >
                    <span>{o.label}</span>
                    {language === o.code && <Check className="w-3.5 h-3.5" />}
                  </button>
                ))}
              </div>
            </>
          )}

          {step === STEP_HOW && (
            <>
              <h2 className="fr-h1">{t("firstRun.howTitle")}</h2>
              <span className="fr-typed">{t("firstRun.howTyped")}</span>
              <div>
                {[1, 2, 3, 4].map((n) => (
                  <div className="fr-row" key={n}>
                    <span className="fr-row-num">{`0${n}`}</span>
                    <div>
                      <div className="fr-row-title">{t(`firstRun.how${n}Title`)}</div>
                      <div className="fr-row-body">{t(`firstRun.how${n}Body`)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          {step === STEP_KEY && (
            <>
              <h2 className="fr-h1">{t("firstRun.stepKey")}</h2>
              <p className="fr-sub">{t("firstRun.stepKeyHint")}</p>

              <button
                type="button"
                data-testid="openrouter-signin"
                disabled={orState === "waiting"}
                onClick={signInWithOpenRouter}
                className="fr-or-btn"
              >
                {orState === "waiting" ? t("firstRun.openrouterWaiting") : t("firstRun.openrouterSignIn")}
              </button>
              {orState === "error" && <p className="fr-err">{orError}</p>}
              {orState === "paid-fallback" && (
                <p className="fr-warn">{t("firstRun.openrouterPaidFallback")}</p>
              )}

              <div className="fr-divider">{t("firstRun.orDivider")}</div>

              <div className="space-y-3">
                <div>
                  <label htmlFor="first-run-provider" className="fr-label">
                    {t("firstRun.providerLabel")}
                  </label>
                  <select
                    id="first-run-provider"
                    data-testid="first-run-provider"
                    value={provider}
                    onChange={(e) => {
                      setProvider(e.target.value);
                      setKeyState("idle");
                      setKeyError("");
                    }}
                    className="fr-field"
                  >
                    {llmProviders.map((p) => (
                      <option key={p.key} value={p.key}>
                        {p.label}
                        {p.native ? " (Native)" : ""}
                      </option>
                    ))}
                  </select>
                  {capabilities && (
                    <p className="fr-cap" data-testid="first-run-capabilities">
                      {t("firstRun.capLine", {
                        tool: capabilities.tool_calling,
                        ctx: capabilities.long_context,
                        cost: capabilities.cost,
                      })}
                    </p>
                  )}
                </div>
                <input
                  data-testid="first-run-key"
                  type="password"
                  value={apiKey}
                  onChange={(e) => {
                    setApiKey(e.target.value);
                    if (keyState === "failed") { setKeyState("idle"); setKeyError(""); }
                  }}
                  placeholder={t("firstRun.keyPlaceholder")}
                  className="fr-field"
                />
              </div>

              <button
                type="button"
                data-testid="first-run-test-save"
                disabled={busy || !apiKey.trim()}
                onClick={() => void testAndSave()}
                className={`fr-test-btn${keyState === "testing" ? " fr-dotload" : ""}`}
              >
                {keyState === "testing" ? t("firstRun.testing") : t("firstRun.testSave")}
              </button>
              {keyState === "ok" && <p className="fr-ok">{t("firstRun.testOk")}</p>}
              {keyState === "failed" && (
                <div className="fr-shake">
                  <p className="fr-err">{keyError}</p>
                  <button
                    type="button"
                    data-testid="first-run-save-anyway"
                    onClick={() => void saveKey()}
                    className="fr-linklike"
                  >
                    {t("firstRun.saveAnyway")}
                  </button>
                </div>
              )}
            </>
          )}

          {step === STEP_HELLO && (
            <>
              <h2 className="fr-h1 font-serif">{t("firstRun.title")}</h2>
              <p className="fr-sub">{t("firstRun.welcomeBody")}</p>
              <label htmlFor="first-run-name" className="fr-label">
                {t("firstRun.namePrompt")}
              </label>
              <input
                id="first-run-name"
                data-testid="first-run-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("firstRun.namePlaceholder")}
                className="fr-field"
              />
              <p className="fr-hint mt-2">{t("firstRun.nameHint")}</p>
            </>
          )}
        </div>

        {/* footer: progress dots + nav */}
        <div className="fr-foot">
          <div className="fr-dots" aria-hidden="true">
            {Array.from({ length: TOTAL_STEPS }, (_, i) => (
              <span key={i} className={`fr-dot${i === step ? " on" : ""}`} />
            ))}
          </div>
          <div className="fr-nav">
            {step === STEP_LANG ? (
              <button type="button" data-testid="first-run-skip" onClick={dismiss} className="fr-ghost">
                {t("firstRun.skip")}
              </button>
            ) : (
              <button
                type="button"
                data-testid="first-run-back"
                onClick={() => setStep((s) => Math.max(0, s - 1))}
                className="fr-ghost"
              >
                {t("firstRun.back")}
              </button>
            )}

            {step === STEP_KEY && (
              <button type="button" data-testid="first-run-add-later" onClick={() => setStep(STEP_HELLO)} className="fr-ghost">
                {t("firstRun.addLater")}
              </button>
            )}

            {(step === STEP_LANG || step === STEP_HOW) && (
              <button
                type="button"
                data-testid="first-run-next"
                onClick={() => setStep((s) => s + 1)}
                className="fr-pri"
              >
                {t("firstRun.next")}
              </button>
            )}
            {step === STEP_HELLO && (
              <button type="button" data-testid="first-run-finish" onClick={finishHello} className="fr-pri">
                {t("firstRun.enter")}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
