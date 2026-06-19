import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import FactsPanel from "../components/settings/FactsPanel";
import ThemeToggle from "../components/layout/ThemeToggle";
import { useAuthStore } from "../stores/authStore";
import type { AppSettings, ProviderOption } from "../types";

// Last-resort list if the backend provider catalog can't be fetched.
const FALLBACK_PROVIDERS: ProviderOption[] = [
  { key: "openai", label: "OpenAI", base_url: "", default_model: "", native: true },
  { key: "anthropic", label: "Anthropic Claude", base_url: "", default_model: "", native: true },
  { key: "gemini", label: "Google Gemini", base_url: "", default_model: "", native: true },
];

export default function Settings() {
  const { t } = useTranslation();
  const token = useAuthStore((s) => s.token);
  const setToken = useAuthStore((s) => s.setToken);
  const [form, setForm] = useState<AppSettings | null>(null);
  const [providers, setProviders] = useState<ProviderOption[]>(FALLBACK_PROVIDERS);
  const [searchProviders, setSearchProviders] = useState<string[]>(["tavily"]);
  const [apiKey, setApiKey] = useState("");
  const [searchKey, setSearchKey] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void api.getSettings().then(setForm);
    void api.listProviders().then(setProviders).catch(() => {
      /* keep FALLBACK_PROVIDERS */
    });
    void api.listSearchProviders().then(setSearchProviders).catch(() => {
      /* keep ["tavily"] */
    });
  }, []);

  if (!form) return <p className="text-white/50">…</p>;

  const update = (patch: Partial<AppSettings>) => setForm({ ...form, ...patch });

  // Picking a provider prefills its base_url + default model (user can still edit).
  const selectProvider = (key: string) => {
    const opt = providers.find((p) => p.key === key);
    update({
      llm_provider: key,
      ...(opt ? { llm_base_url: opt.base_url, llm_model: opt.default_model } : {}),
    });
  };

  // Always show the current value, even if it's not in the fetched catalog.
  const options = providers.some((p) => p.key === form.llm_provider)
    ? providers
    : [
        { key: form.llm_provider, label: form.llm_provider, base_url: "", default_model: "", native: false },
        ...providers,
      ];

  const save = async () => {
    const body: Partial<AppSettings> = {
      llm_provider: form.llm_provider,
      llm_model: form.llm_model,
      llm_base_url: form.llm_base_url,
      language: form.language,
      search_provider: form.search_provider,
    };
    if (apiKey) body.llm_api_key = apiKey;
    if (searchKey) body.search_api_key = searchKey;
    const updated = await api.updateSettings(body);
    setForm(updated);
    setApiKey("");
    setSearchKey("");
    if (tokenInput) {
      setToken(tokenInput);
      setTokenInput("");
    }
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="mx-auto max-w-xl">
      <h1 className="mb-6 text-2xl font-semibold">{t("settings.title")}</h1>

      <section className="space-y-4 rounded-xl border border-white/10 bg-white/5 p-5">
        <h2 className="font-medium text-amber">{t("settings.llm_section")}</h2>

        <label className="block text-sm">
          {t("settings.provider")}
          <select
            value={form.llm_provider}
            onChange={(e) => selectProvider(e.target.value)}
            className="mt-1 w-full rounded-lg bg-white/10 px-3 py-2"
          >
            {options.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm">
          {t("settings.model")}
          <input
            value={form.llm_model}
            onChange={(e) => update({ llm_model: e.target.value })}
            className="mt-1 w-full rounded-lg bg-white/10 px-3 py-2"
          />
        </label>

        <label className="block text-sm">
          {t("settings.base_url")}
          <input
            value={form.llm_base_url}
            onChange={(e) => update({ llm_base_url: e.target.value })}
            className="mt-1 w-full rounded-lg bg-white/10 px-3 py-2"
          />
        </label>

        <label className="block text-sm">
          {t("settings.api_key")}
          <input
            type="password"
            value={apiKey}
            placeholder={form.llm_api_key || "sk-..."}
            onChange={(e) => setApiKey(e.target.value)}
            className="mt-1 w-full rounded-lg bg-white/10 px-3 py-2"
          />
          <span className="text-xs text-white/40">{t("settings.api_key_hint")}</span>
        </label>
      </section>

      <section className="mt-4 space-y-4 rounded-xl border border-white/10 bg-white/5 p-5">
        <h2 className="font-medium text-amber">{t("settings.search_section")}</h2>

        <label className="block text-sm">
          {t("settings.search_provider")}
          <select
            value={form.search_provider}
            onChange={(e) => update({ search_provider: e.target.value })}
            className="mt-1 w-full rounded-lg bg-white/10 px-3 py-2"
          >
            {searchProviders.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-sm">
          {t("settings.search_api_key")}
          <input
            type="password"
            value={searchKey}
            placeholder={form.search_api_key || "tvly-..."}
            onChange={(e) => setSearchKey(e.target.value)}
            className="mt-1 w-full rounded-lg bg-white/10 px-3 py-2"
          />
          <span className="text-xs text-white/40">{t("settings.search_api_key_hint")}</span>
        </label>
      </section>

      <section className="mt-4 space-y-3 rounded-xl border border-white/10 bg-white/5 p-5">
        <h2 className="font-medium text-amber">{t("settings.server_section")}</h2>
        <label className="block text-sm">
          {t("settings.api_token")}
          <input
            type="password"
            value={tokenInput}
            placeholder={token ? "••••••••" : t("settings.api_token")}
            onChange={(e) => setTokenInput(e.target.value)}
            className="mt-1 w-full rounded-lg bg-white/10 px-3 py-2"
          />
          <span className="text-xs text-white/40">{t("settings.api_token_hint")}</span>
        </label>
      </section>

      <section className="mt-4 flex items-center justify-between rounded-xl border border-white/10 bg-white/5 p-5">
        <span className="text-sm">{t("settings.theme")}</span>
        <ThemeToggle />
      </section>

      <FactsPanel />

      <button onClick={() => void save()} className="mt-6 rounded-lg bg-amber px-5 py-2.5 font-medium text-black">
        {t("settings.save")}
      </button>
      {saved && <span className="ml-3 text-sm text-green-400">{t("settings.saved")}</span>}
    </div>
  );
}
