import type { ComponentProps } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Sidebar from "../components/Sidebar";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";

const noop = () => {};
const props: ComponentProps<typeof Sidebar> = {
  threads: [], activeThreadId: "", onSelectThread: noop, onAddThread: noop,
  activeSection: "arslan", onChangeSection: noop,
  onDistillThread: noop, onArchiveThread: noop, onUnarchiveThread: noop,
  onDeleteThread: noop, backendStatus: "online",
};
const labels = {
  en: ["Online", "Offline", "Connecting"],
  zh: ["在线", "离线", "连接中"],
  ja: ["オンライン", "オフライン", "接続中"],
  es: ["En línea", "Sin conexión", "Conectando"],
  de: ["Erreichbar", "Nicht erreichbar", "Verbindung wird hergestellt"],
  fr: ["En ligne", "Hors ligne", "Connexion"],
};

afterEach(async () => { cleanup(); await i18n.changeLanguage("en"); });

describe("actual sidebar service status in six languages", () => {
  it.each(SUPPORTED_LANGUAGES)("has explicit execution posture labels in %s", async language => {
    await i18n.changeLanguage(language);
    for (const key of ["executionOptions", "readOnlyAutomatic", "confirmCommands"]) {
      expect(String(i18n.t(`workspace.${key}`))).not.toBe(`workspace.${key}`);
    }
    expect(i18n.t('workspace.confirmCommands')).not.toBe(i18n.t('workspace.readOnlyAutomatic'));
  });
  it.each(SUPPORTED_LANGUAGES)("renders all three states in %s", async language => {
    await i18n.changeLanguage(language);
    const view = render(<Sidebar {...props} />);
    expect(screen.getByText(labels[language][0])).toBeVisible();
    view.rerender(<Sidebar {...props} backendStatus="offline" />);
    expect(screen.getByText(labels[language][1])).toBeVisible();
    view.rerender(<Sidebar {...props} backendStatus="checking" />);
    expect(screen.getByText(labels[language][2])).toBeVisible();
  });

  // 0.1.42: the composer invites doing work, and no longer describes Arslan
  // as a coordinator of experts (they live in the capability library).
  it.each(SUPPORTED_LANGUAGES)("both %s composers address Arslan without team vocabulary", async language => {
    await i18n.changeLanguage(language);
    for (const key of ["orchestrator.placeholder_empty", "orchestrator.placeholder_chat"]) {
      const value = String(i18n.t(key));
      expect(value).not.toMatch(/spawns?|分身|スポーン|coordinat|协调|調整|coordin|koordin/i);
      expect(value).toContain("Arslan");
    }
  });

  it.each(SUPPORTED_LANGUAGES)("never says 分身 anywhere in %s", async language => {
    await i18n.changeLanguage(language);
    const all = JSON.stringify(i18n.getResourceBundle(language, "translation"));
    expect(all).not.toContain("分身");
  });
});
