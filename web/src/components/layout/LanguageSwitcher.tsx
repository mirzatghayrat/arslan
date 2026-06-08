import { useTranslation } from "react-i18next";
import { SUPPORTED_LANGUAGES } from "../../i18n";

const LABELS: Record<string, string> = {
  en: "English",
  zh: "中文",
  ja: "日本語",
  es: "Español",
  de: "Deutsch",
  fr: "Français",
};

export default function LanguageSwitcher() {
  const { i18n } = useTranslation();
  return (
    <select
      value={i18n.resolvedLanguage}
      onChange={(e) => void i18n.changeLanguage(e.target.value)}
      aria-label="Language"
      className="rounded-lg bg-white/10 px-2 py-2 text-sm"
    >
      {SUPPORTED_LANGUAGES.map((lng) => (
        <option key={lng} value={lng}>
          {LABELS[lng]}
        </option>
      ))}
    </select>
  );
}
