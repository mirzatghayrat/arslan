import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import de from "./locales/de.json";
import en from "./locales/en.json";
import es from "./locales/es.json";
import fr from "./locales/fr.json";
import ja from "./locales/ja.json";
import zh from "./locales/zh.json";
import { companionMessages } from "./locales/companion";
import { taskMessages } from "./locales/tasks";
import { methodMessages } from "./locales/methods";

export const SUPPORTED_LANGUAGES = ["en", "zh", "ja", "es", "de", "fr"] as const;
export type Lang = (typeof SUPPORTED_LANGUAGES)[number];

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: { ...en, companion: companionMessages.en, tasks: taskMessages.en, methods: methodMessages.en } },
      zh: { translation: { ...zh, companion: companionMessages.zh, tasks: taskMessages.zh, methods: methodMessages.zh } },
      ja: { translation: { ...ja, companion: companionMessages.ja, tasks: taskMessages.ja, methods: methodMessages.ja } },
      es: { translation: { ...es, companion: companionMessages.es, tasks: taskMessages.es, methods: methodMessages.es } },
      de: { translation: { ...de, companion: companionMessages.de, tasks: taskMessages.de, methods: methodMessages.de } },
      fr: { translation: { ...fr, companion: companionMessages.fr, tasks: taskMessages.fr, methods: methodMessages.fr } },
    },
    fallbackLng: "en",
    supportedLngs: [...SUPPORTED_LANGUAGES],
    load: "languageOnly",
    interpolation: { escapeValue: false },
    detection: { order: ["localStorage", "navigator"], caches: ["localStorage"] },
  });

export default i18n;
