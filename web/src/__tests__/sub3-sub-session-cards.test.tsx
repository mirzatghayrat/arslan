/** SUB3 (v0.1.64): a sub-session's card is shown in the conversation that started it (the frame says `sub_session`).
 *  Its "In this conversation" would read as this conversation's, but the server grants it to the sub-session only, so
 *  the choice says "In this sub-session" — with what it covers, as "In this conversation" says it. The answer it sends
 *  is still the `conversation` scope. Real i18n, all six languages. */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import AskSlot from "../components/AskSlot";
import WorkspaceWriteCard from "../components/WorkspaceWriteCard";
import { initialArslanState, useArslanStore } from "../stores/arslanStore";

const LANGS = ["en", "zh", "ja", "es", "de", "fr"] as const;
beforeEach(() => { useArslanStore.setState(initialArslanState(), true); });
afterEach(() => { cleanup(); });
const frame = (f: Record<string, unknown>) => act(() => { useArslanStore.getState().handleFrame(f as never); });
const choice = (testId: string) => screen.getByTestId(`${testId}-conversation`).closest("label")!;

// [the card, its frame, its scope picker's test id, what its "In this conversation" covers (a key), its Allow]
const CARDS: [string, Record<string, unknown>, string, string | null, string][] = [
  ["a command card", { type: "propose_run_command", call_id: "c1", pretty: "ls", reason: "" }, "runcmd-scope", null, "runcmd-run"],
  ["a write card", { type: "propose_workspace_write", call_id: "w1", workspace: "/w", action: "write_file", path: "a" },
    "wswrite-scope", "wswrite.anyFile", "wswrite-allow"],
  ["a schedule card", { type: "propose_schedule", call_id: "s1", name: "n", when: "every: 60" }, "schedule-choice",
    "schedgrant.anyTask", "schedule-allow"],
  ["an action card", { type: "propose_action", call_id: "a1", kind: "app", target: "x", detail: "", title: "Use x?" },
    "action-scope", null, "action-allow"],
];

describe("a sub-session's card says whose grant it is", () => {
  it.each(CARDS)("%s says In this sub-session", async (_name, card, testId, covers) => {
    await i18n.changeLanguage("en");
    render(<AskSlot send={vi.fn()} />);
    frame({ ...card, options: ["once", "conversation"], background: true, sub_session: true });
    const words = covers ? i18n.t("kit.scope.subSessionFor", { label: i18n.t(covers) }) : i18n.t("kit.scope.subSession");
    expect(choice(testId)).toHaveTextContent(String(words));
    expect(choice(testId)).not.toHaveTextContent(/conversation/i);
  });

  it.each(CARDS)("%s of the conversation's own keeps In this conversation", async (_name, card, testId) => {
    await i18n.changeLanguage("en");
    render(<AskSlot send={vi.fn()} />);
    frame({ ...card, options: ["once", "conversation"], background: true });
    expect(choice(testId)).toHaveTextContent(/In this conversation/);
  });

  it.each(LANGS)("%s: the words exist and differ from the conversation's", async (lang) => {
    await i18n.changeLanguage(lang);
    for (const key of ["subSession", "subSessionFor"]) {
      expect(i18n.exists(`kit.scope.${key}`, { lng: lang, fallbackLng: false } as never)).toBe(true);
    }
    expect(i18n.t("kit.scope.subSession")).not.toBe(i18n.t("kit.scope.conversation"));
  });

  it("the answer is still the conversation scope, which the server grants to the sub-session", async () => {
    await i18n.changeLanguage("en");
    const onConfirm = vi.fn();
    render(<WorkspaceWriteCard callId="w1" workspace="/w" action="write_file" path="a" background subSession
      options={["once", "conversation"]} onConfirm={onConfirm} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByTestId("wswrite-scope-conversation"));
    fireEvent.click(screen.getByTestId("wswrite-allow"));
    expect(onConfirm).toHaveBeenCalledWith("w1", "conversation");
  });
});
