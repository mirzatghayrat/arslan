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
import { validationMessages } from "./locales/validation";
import { dockMessages } from "./locales/dock";
import { inputMessages } from "./locales/inputs";
import { workspaceMessages } from "./locales/workspace";
import { connectionMessages } from "./locales/connections";
import { uiMessages } from "./locales/ui";
import { designMessages } from "./locales/design";
import { catalogDisplayMessages as catalogMessages } from "./locales/catalog";

export const SUPPORTED_LANGUAGES = ["en", "zh", "ja", "es", "de", "fr"] as const;
export type Lang = (typeof SUPPORTED_LANGUAGES)[number];

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: { ...en, design: designMessages.en, catalogUI: catalogMessages.en, companion: companionMessages.en, tasks: taskMessages.en, methods: methodMessages.en, validation: validationMessages.en, dock: dockMessages.en, inputs: inputMessages.en, workspace: workspaceMessages.en, connectionsUI: connectionMessages.en, ui: uiMessages.en } },
      zh: { translation: { ...zh, design: designMessages.zh, catalogUI: catalogMessages.zh, companion: companionMessages.zh, tasks: taskMessages.zh, methods: methodMessages.zh, validation: validationMessages.zh, dock: dockMessages.zh, inputs: inputMessages.zh, workspace: workspaceMessages.zh, connectionsUI: connectionMessages.zh, ui: uiMessages.zh } },
      ja: { translation: { ...ja, design: designMessages.ja, catalogUI: catalogMessages.ja, companion: companionMessages.ja, tasks: taskMessages.ja, methods: methodMessages.ja, validation: validationMessages.ja, dock: dockMessages.ja, inputs: inputMessages.ja, workspace: workspaceMessages.ja, connectionsUI: connectionMessages.ja, ui: uiMessages.ja } },
      es: { translation: { ...es, design: designMessages.es, catalogUI: catalogMessages.es, companion: companionMessages.es, tasks: taskMessages.es, methods: methodMessages.es, validation: validationMessages.es, dock: dockMessages.es, inputs: inputMessages.es, workspace: workspaceMessages.es, connectionsUI: connectionMessages.es, ui: uiMessages.es } },
      de: { translation: { ...de, design: designMessages.de, catalogUI: catalogMessages.de, companion: companionMessages.de, tasks: taskMessages.de, methods: methodMessages.de, validation: validationMessages.de, dock: dockMessages.de, inputs: inputMessages.de, workspace: workspaceMessages.de, connectionsUI: connectionMessages.de, ui: uiMessages.de } },
      fr: { translation: { ...fr, design: designMessages.fr, catalogUI: catalogMessages.fr, companion: companionMessages.fr, tasks: taskMessages.fr, methods: methodMessages.fr, validation: validationMessages.fr, dock: dockMessages.fr, inputs: inputMessages.fr, workspace: workspaceMessages.fr, connectionsUI: connectionMessages.fr, ui: uiMessages.fr } },
    },
    fallbackLng: "en",
    supportedLngs: [...SUPPORTED_LANGUAGES],
    load: "languageOnly",
    interpolation: { escapeValue: false },
    detection: { order: ["localStorage", "navigator"], caches: ["localStorage"] },
  });

export default i18n;
