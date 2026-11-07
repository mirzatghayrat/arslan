/**
 * SMART-8 delete cards (#686): the card says what Allow really does. The mode is the server's
 * (`delete_to_trash.card_mode`), on the frame as `delete_mode`; every mode has its words, in every language, and a
 * move to the Trash never reads as a permanent delete, or the other way round.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { commandRisk, deletePurpose, summarize } from "../lib/commandSummary";
import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import es from "../locales/es.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, params?: Record<string, unknown>) =>
    params && "count" in params ? `${key}:${params.count}` : key }),
}));

import RunCommandCard from "../components/RunCommandCard";

const card = (deleteMode?: string, deleteTargets?: string[]) => render(
  <RunCommandCard callId="c1" pretty="rm -rf ~/old" rules={["delete-outside"]} deleteMode={deleteMode}
    deleteTargets={deleteTargets} onConfirm={vi.fn()} onCancel={vi.fn()} />);

describe("the risk row by delete mode", () => {
  it.each([
    ["trash", "warn", "rule.delete-outside-trash"],
    ["protected", "warn", "rule.delete-outside-protected"],
    ["sandboxed", "irreversible", "rule.delete-outside-sandboxed"],
    ["permanent", "irreversible", "rule.delete-outside"],
    [undefined, "irreversible", "rule.delete-outside"],
  ])("%s", (mode, level, key) => {
    const risk = commandRisk({ rules: ["delete-outside"], deleteMode: mode });
    expect(risk.level).toBe(level);
    expect(risk.keys.map(k => k.key)).toEqual([key]);
  });

  it("a mode says nothing about another rule, and another rule still raises the row", () => {
    expect(commandRisk({ rules: ["upload"], deleteMode: "trash" }).keys.map(k => k.key)).toEqual(["rule.upload"]);
    expect(commandRisk({ rules: ["delete-outside", "publish"], deleteMode: "trash" }).level).toBe("irreversible");
  });
});

describe("the purpose by delete mode", () => {
  const read = summarize("rm -rf ~/old ~/older").purpose;
  it("a move to the Trash says so, with its count", () => {
    for (const mode of ["trash", "protected"]) expect(deletePurpose(read, mode)).toEqual({ ...read, key: "toTrash" });
  });
  it("anything else stays a delete", () => {
    for (const mode of ["permanent", "sandboxed", undefined]) expect(deletePurpose(read, mode).key).toBe("delete");
    expect(deletePurpose(summarize("git status").purpose, "trash").key).not.toBe("toTrash");
  });
});

describe("the card", () => {
  it("a move to the Trash leads with that and is not drawn as irreversible", () => {
    card("trash");
    expect(screen.getByTestId("runcmd-purpose")).toHaveTextContent("runcmd.purpose.toTrash");
    expect(document.body.textContent).toContain("runcmd.risk.rule.delete-outside-trash");
    expect(document.body.textContent).not.toContain("runcmd.risk.rule.delete-outside ");
  });
  it("a permanent delete keeps the delete purpose and its line", () => {
    card("permanent");
    expect(screen.getByTestId("runcmd-purpose")).toHaveTextContent("runcmd.purpose.delete");
    expect(document.body.textContent).toContain("runcmd.risk.rule.delete-outside");
    expect(document.body.textContent).not.toContain("delete-outside-trash");
  });
  it("touches come from the server's targets when it read them", () => {
    card("trash", ["~/from-the-server"]);
    expect(document.body.textContent).toContain("~/from-the-server");
  });
});

describe("every language has every line", () => {
  it.each(Object.entries({ en, zh, ja, es, de, fr }))("%s", (_lang, text) => {
    const run = (text as typeof en).runcmd;
    expect(run.purpose.toTrash).toBeTruthy();
    expect(run.purpose.toTrash_one).toBeTruthy();
    for (const mode of ["trash", "protected", "sandboxed"] as const) {
      expect(run.risk.rule[`delete-outside-${mode}`]).toBeTruthy();
    }
  });
});
