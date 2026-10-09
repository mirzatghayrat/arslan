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
import { memoryPageMessages } from "./locales/memoryPage";
import { capabilityListMessages } from "./locales/capabilityList";
import { projectsMessages } from "./locales/projects";
import { discoverMessages } from "./locales/discover";
import { memoryEvidenceMessages } from "./locales/memoryEvidence";
import { taskMessages } from "./locales/tasks";
import { methodMessages } from "./locales/methods";
import { validationMessages } from "./locales/validation";
import { dockMessages } from "./locales/dock";
import { inputMessages } from "./locales/inputs";
import { workspaceMessages } from "./locales/workspace";
import { jobMessages } from "./locales/jobs";
import { handsMessages } from "./locales/hands";
import { proactiveMessages } from "./locales/proactive";
import { panelMessages, activityMessages } from "./locales/panel";
import { processMessages } from "./locales/process";
import { workbenchMessages } from "./locales/workbench";
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
      en: { translation: { ...en, memoryEvidence: memoryEvidenceMessages.en, design: designMessages.en, catalogUI: catalogMessages.en, companion: companionMessages.en, memoryPage: memoryPageMessages.en, capabilityList: capabilityListMessages.en, projectsUI: projectsMessages.en, discover: discoverMessages.en, tasks: taskMessages.en, methods: methodMessages.en, validation: validationMessages.en, dock: dockMessages.en, inputs: inputMessages.en, workspace: workspaceMessages.en, jobs: jobMessages.en, hands: handsMessages.en, proactive: proactiveMessages.en, panel: panelMessages.en, activityPage: activityMessages.en, process: processMessages.en, workbench: workbenchMessages.en, connectionsUI: connectionMessages.en, ui: uiMessages.en } },
      zh: { translation: { ...zh, memoryEvidence: memoryEvidenceMessages.zh, design: designMessages.zh, catalogUI: catalogMessages.zh, companion: companionMessages.zh, memoryPage: memoryPageMessages.zh, capabilityList: capabilityListMessages.zh, projectsUI: projectsMessages.zh, discover: discoverMessages.zh, tasks: taskMessages.zh, methods: methodMessages.zh, validation: validationMessages.zh, dock: dockMessages.zh, inputs: inputMessages.zh, workspace: workspaceMessages.zh, jobs: jobMessages.zh, hands: handsMessages.zh, proactive: proactiveMessages.zh, panel: panelMessages.zh, activityPage: activityMessages.zh, process: processMessages.zh, workbench: workbenchMessages.zh, connectionsUI: connectionMessages.zh, ui: uiMessages.zh } },
      ja: { translation: { ...ja, memoryEvidence: memoryEvidenceMessages.ja, design: designMessages.ja, catalogUI: catalogMessages.ja, companion: companionMessages.ja, memoryPage: memoryPageMessages.ja, capabilityList: capabilityListMessages.ja, projectsUI: projectsMessages.ja, discover: discoverMessages.ja, tasks: taskMessages.ja, methods: methodMessages.ja, validation: validationMessages.ja, dock: dockMessages.ja, inputs: inputMessages.ja, workspace: workspaceMessages.ja, jobs: jobMessages.ja, hands: handsMessages.ja, proactive: proactiveMessages.ja, panel: panelMessages.ja, activityPage: activityMessages.ja, process: processMessages.ja, workbench: workbenchMessages.ja, connectionsUI: connectionMessages.ja, ui: uiMessages.ja } },
      es: { translation: { ...es, memoryEvidence: memoryEvidenceMessages.es, design: designMessages.es, catalogUI: catalogMessages.es, companion: companionMessages.es, memoryPage: memoryPageMessages.es, capabilityList: capabilityListMessages.es, projectsUI: projectsMessages.es, discover: discoverMessages.es, tasks: taskMessages.es, methods: methodMessages.es, validation: validationMessages.es, dock: dockMessages.es, inputs: inputMessages.es, workspace: workspaceMessages.es, jobs: jobMessages.es, hands: handsMessages.es, proactive: proactiveMessages.es, panel: panelMessages.es, activityPage: activityMessages.es, process: processMessages.es, workbench: workbenchMessages.es, connectionsUI: connectionMessages.es, ui: uiMessages.es } },
      de: { translation: { ...de, memoryEvidence: memoryEvidenceMessages.de, design: designMessages.de, catalogUI: catalogMessages.de, companion: companionMessages.de, memoryPage: memoryPageMessages.de, capabilityList: capabilityListMessages.de, projectsUI: projectsMessages.de, discover: discoverMessages.de, tasks: taskMessages.de, methods: methodMessages.de, validation: validationMessages.de, dock: dockMessages.de, inputs: inputMessages.de, workspace: workspaceMessages.de, jobs: jobMessages.de, hands: handsMessages.de, proactive: proactiveMessages.de, panel: panelMessages.de, activityPage: activityMessages.de, process: processMessages.de, workbench: workbenchMessages.de, connectionsUI: connectionMessages.de, ui: uiMessages.de } },
      fr: { translation: { ...fr, memoryEvidence: memoryEvidenceMessages.fr, design: designMessages.fr, catalogUI: catalogMessages.fr, companion: companionMessages.fr, memoryPage: memoryPageMessages.fr, capabilityList: capabilityListMessages.fr, projectsUI: projectsMessages.fr, discover: discoverMessages.fr, tasks: taskMessages.fr, methods: methodMessages.fr, validation: validationMessages.fr, dock: dockMessages.fr, inputs: inputMessages.fr, workspace: workspaceMessages.fr, jobs: jobMessages.fr, hands: handsMessages.fr, proactive: proactiveMessages.fr, panel: panelMessages.fr, activityPage: activityMessages.fr, process: processMessages.fr, workbench: workbenchMessages.fr, connectionsUI: connectionMessages.fr, ui: uiMessages.fr } },
    },
    fallbackLng: "en",
    supportedLngs: [...SUPPORTED_LANGUAGES],
    load: "languageOnly",
    interpolation: { escapeValue: false },
    detection: { order: ["localStorage", "navigator"], caches: ["localStorage"] },
  });

export default i18n;
