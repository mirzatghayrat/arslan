/**
 * FirstRunWizard — the first-touch onboarding overlay, shown once when no
 * provider/model is configured yet (see lib/firstRun.firstRunShouldShow). It
 * replaces the bare NoModelHint as the FIRST-run experience; NoModelHint stays
 * as the inline nudge for later visits.
 *
 * Three minimal steps: welcome → pick language → connect at least one BYOK key.
 * It reuses the existing provider-config save path (addProviderConfig) and the
 * canonical LANGUAGE_OPTIONS list. Dismissible at any point ("Skip"/"Add
 * later"); on finish OR dismiss it persists the firstRunSeen flag so it never
 * nags again.
 */

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Sparkles, ChevronLeft, ChevronRight, X, KeyRound, Languages, Check } from "lucide-react";
import type { ProviderOption, ProviderConfig } from "../api/client.types";
import { addProviderConfig, api } from "../api/client";
import { LANGUAGE_OPTIONS } from "../lib/languages";
import { setFirstRunSeen } from "../lib/firstRun";

interface FirstRunWizardProps {
  llmProviders: ProviderOption[];
  /** Called with the newly created config so the parent can append it. */
  onAdded: (config: ProviderConfig) => void;
  /** Called after the wizard closes (finish or dismiss) so the parent hides it. */
  onClose: () => void;
}

const TOTAL_STEPS = 3;

export default function FirstRunWizard({ llmProviders, onAdded, onClose }: FirstRunWizardProps) {
  const { t, i18n } = useTranslation();
  const [step, setStep] = useState(0);
  const [language, setLanguage] = useState<string>(i18n.language || "en");
  const [provider, setProvider] = useState<string>(llmProviders[0]?.key ?? "");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);

  const finish = () => {
    setFirstRunSeen();
    onClose();
  };

  const dismiss = () => {
    setFirstRunSeen();
    onClose();
  };

  const pickLanguage = (code: string) => {
    setLanguage(code);
    i18n.changeLanguage(code);
    // Best-effort persist to backend settings so the choice survives a reload.
    api.updateSettings({ language: code }).catch(() => {});
  };

  const handleFinish = async () => {
    const info = llmProviders.find((p) => p.key === provider);
    const key = apiKey.trim();
    // "Add later" path: no key entered → just mark seen and close.
    if (!info || !key) {
      finish();
      return;
    }
    setSaving(true);
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
    } finally {
      setSaving(false);
      finish();
    }
  };

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-[70] p-4 animate-fade-in">
      <div className="w-full max-w-lg bg-surface/95 border border-border-strong rounded-2xl shadow-2xl shadow-primary/20 overflow-hidden select-none">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border/80 flex items-center justify-between bg-background">
          <div className="flex items-center gap-2">
            <img src="/arslan-mark.png" alt="Arslan" className="w-6 h-6 object-contain arslan-mark" draggable={false} />
            <span className="text-[10px] font-mono text-subtle-foreground uppercase tracking-widest">
              {t("firstRun.stepOf", { current: step + 1, total: TOTAL_STEPS })}
            </span>
          </div>
          <button
            type="button"
            data-testid="first-run-dismiss"
            onClick={dismiss}
            className="text-muted-foreground hover:text-foreground transition-colors"
            title={t("firstRun.skip")}
          >
            <X className="w-4.5 h-4.5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-7 min-h-[240px] flex flex-col">
          {/* Step 0 — welcome */}
          {step === 0 && (
            <div className="flex-1 flex flex-col items-center justify-center text-center space-y-4 animate-fade-in">
              <div className="w-12 h-12 rounded-2xl bg-primary/10 border border-primary/30 flex items-center justify-center">
                <Sparkles className="w-6 h-6 text-primary" />
              </div>
              <h2 className="text-xl font-serif font-medium text-foreground tracking-tight">
                {t("firstRun.title")}
              </h2>
              <p className="text-xs text-muted-foreground font-sans leading-relaxed max-w-sm">
                {t("firstRun.welcomeBody")}
              </p>
            </div>
          )}

          {/* Step 1 — language */}
          {step === 1 && (
            <div className="flex-1 space-y-4 animate-fade-in">
              <div className="flex items-center gap-2">
                <Languages className="w-4 h-4 text-primary" />
                <h2 className="text-sm font-bold text-foreground font-sans">{t("firstRun.stepLanguage")}</h2>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {LANGUAGE_OPTIONS.map((o) => (
                  <button
                    key={o.code}
                    type="button"
                    data-testid={`first-run-lang-${o.code}`}
                    onClick={() => pickLanguage(o.code)}
                    className={`flex items-center justify-between px-3.5 py-2.5 rounded-xl border text-xs font-sans transition-all ${
                      language === o.code
                        ? "border-primary/60 bg-primary/10 text-primary font-bold"
                        : "border-border bg-surface text-muted-foreground hover:border-primary/30 hover:text-foreground"
                    }`}
                  >
                    <span>{o.label}</span>
                    {language === o.code && <Check className="w-3.5 h-3.5" />}
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-subtle-foreground font-sans">{t("firstRun.stepLanguageHint")}</p>
            </div>
          )}

          {/* Step 2 — connect a model (BYOK) */}
          {step === 2 && (
            <div className="flex-1 space-y-4 animate-fade-in">
              <div className="flex items-center gap-2">
                <KeyRound className="w-4 h-4 text-primary" />
                <h2 className="text-sm font-bold text-foreground font-sans">{t("firstRun.stepKey")}</h2>
              </div>
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <label
                    htmlFor="first-run-provider"
                    className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide"
                  >
                    {t("firstRun.providerLabel")}
                  </label>
                  <select
                    id="first-run-provider"
                    data-testid="first-run-provider"
                    value={provider}
                    onChange={(e) => setProvider(e.target.value)}
                    className="w-full bg-surface border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-xl px-3.5 py-2.5 text-xs text-foreground focus:outline-none transition-all font-sans"
                  >
                    {llmProviders.map((p) => (
                      <option key={p.key} value={p.key}>
                        {p.label}
                        {p.native ? " (Native)" : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1.5">
                  <input
                    data-testid="first-run-key"
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={t("firstRun.keyPlaceholder")}
                    className="w-full bg-surface border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-xl px-3.5 py-2.5 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-mono"
                  />
                </div>
              </div>
              <p className="text-[10px] text-subtle-foreground font-sans leading-relaxed">{t("firstRun.stepKeyHint")}</p>
            </div>
          )}

          {/* Footer nav */}
          <div className="flex items-center justify-between pt-6 mt-auto border-t border-border/50">
            {step > 0 ? (
              <button
                type="button"
                data-testid="first-run-back"
                onClick={() => setStep((s) => Math.max(0, s - 1))}
                className="flex items-center gap-1 px-3 py-2 text-[11px] font-mono font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
                {t("firstRun.back")}
              </button>
            ) : (
              <button
                type="button"
                data-testid="first-run-skip"
                onClick={dismiss}
                className="px-3 py-2 text-[11px] font-mono font-medium text-subtle-foreground hover:text-foreground transition-colors"
              >
                {t("firstRun.skip")}
              </button>
            )}

            {step < TOTAL_STEPS - 1 ? (
              <button
                type="button"
                data-testid="first-run-next"
                onClick={() => setStep((s) => Math.min(TOTAL_STEPS - 1, s + 1))}
                className="flex items-center gap-1.5 px-4 py-2 bg-primary hover:bg-primary-hover text-primary-foreground text-xs font-bold font-sans uppercase rounded-lg transition-colors shadow-lg shadow-primary/10"
              >
                {step === 0 ? t("firstRun.getStarted") : t("firstRun.next")}
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  data-testid="first-run-add-later"
                  onClick={finish}
                  className="px-3 py-2 text-[11px] font-mono font-medium text-subtle-foreground hover:text-foreground transition-colors"
                >
                  {t("firstRun.addLater")}
                </button>
                <button
                  type="button"
                  data-testid="first-run-finish"
                  onClick={handleFinish}
                  disabled={saving}
                  className="flex items-center gap-1.5 px-4 py-2 bg-primary hover:bg-primary-hover text-primary-foreground text-xs font-bold font-sans uppercase rounded-lg transition-colors shadow-lg shadow-primary/10 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {t("firstRun.finish")}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
