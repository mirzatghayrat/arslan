/** 0.1.61 §A4 (PR 2b final review): "In this conversation" says what it covers when that is more than the request on the card.
 *  The server grants a command card's "In this conversation" to its KIND of command (the rules it matched: every `rm`, every
 *  `git push` — approvals._command_request), a schedule card's to creating ANY scheduled task (target "*"), and a write card's to
 *  any file in the folder. A bare "In this conversation" under "Run `rm -rf build`?" reads as that one command; under
 *  "How long this yes lasts" it promises less than it grants. Real i18n, all six languages. */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import i18n from "../i18n";
import RunCommandCard from "../components/RunCommandCard";
import ScheduleGrantCard from "../components/ScheduleGrantCard";
import WorkspaceWriteCard from "../components/WorkspaceWriteCard";

const LANGS = ["en", "zh", "ja", "es", "de", "fr"] as const;
afterEach(() => { cleanup(); });
const conversationChoice = (scope: string) => screen.getByTestId(`${scope}-conversation`).closest("label")!;

describe("In this conversation says what it covers", () => {
  it.each(LANGS)("%s: on a command card it names the kind of command, as Always does", async (lang) => {
    await i18n.changeLanguage(lang);
    render(<RunCommandCard callId="c" pretty="rm -rf build" reason="deletes files" permKind="command"
      options={["once", "conversation", "always"]} alwaysLabel="deletes files, recursive delete" onConfirm={() => {}} onCancel={() => {}} />);
    expect(conversationChoice("runcmd-scope")).toHaveTextContent("deletes files, recursive delete");
    expect(conversationChoice("runcmd-scope")).toHaveTextContent(String(i18n.t("kit.scope.conversationFor", { label: "deletes files, recursive delete" })));
  });

  it("a command card with nothing to name (it matched no rule: the grant is for this text) keeps the plain words", async () => {
    await i18n.changeLanguage("en");
    render(<RunCommandCard callId="c" pretty="ls" reason="" permKind="command" options={["once", "conversation"]}
      onConfirm={() => {}} onCancel={() => {}} />);
    expect(conversationChoice("runcmd-scope")).toHaveTextContent(/^In this conversation$/);
  });

  it("a command frame that carries another kind (an app card may ride one) keeps the plain words: its grant is not for the command's rules", async () => {
    await i18n.changeLanguage("en");
    render(<RunCommandCard callId="c" pretty={'osascript -e \'tell application "Notes" to activate\''} reason="" permKind="app"
      options={["task", "conversation", "always"]} alwaysLabel="Notes" onConfirm={() => {}} onCancel={() => {}} />);
    expect(conversationChoice("runcmd-scope")).toHaveTextContent(/^In this conversation$/);
  });

  it("a command card of an old frame (no permission kind) keeps the plain words too", async () => {
    await i18n.changeLanguage("en");
    render(<RunCommandCard callId="c" pretty="rm -rf build" reason="" options={["once", "conversation", "always"]}
      alwaysLabel="deletes files" onConfirm={() => {}} onCancel={() => {}} />);
    expect(conversationChoice("runcmd-scope")).toHaveTextContent(/^In this conversation$/);
  });

  it.each(LANGS)("%s: on a schedule card it says any scheduled task, not this one", async (lang) => {
    await i18n.changeLanguage(lang);
    render(<ScheduleGrantCard callId="s" name="Daily digest" when="every: 86400" options={["once", "conversation"]}
      onConfirm={() => {}} onCancel={() => {}} />);
    expect(conversationChoice("schedule-choice")).toHaveTextContent(String(i18n.t("kit.scope.conversationFor", { label: String(i18n.t("schedgrant.anyTask")) })));
  });

  it.each(LANGS)("%s: on a write card it says any file in the folder, not this one", async (lang) => {
    await i18n.changeLanguage(lang);
    render(<WorkspaceWriteCard callId="w" workspace="/Users/me/Arslan" action="write_file" path="notes.md" options={["once", "conversation"]}
      onConfirm={() => {}} onCancel={() => {}} />);
    expect(conversationChoice("wswrite-scope")).toHaveTextContent(String(i18n.t("kit.scope.conversationFor", { label: String(i18n.t("wswrite.anyFile")) })));
  });

  it("an app card's choices are unchanged: its grant is the app itself, which the card already names", async () => {
    await i18n.changeLanguage("en");
    const ActionApprovalCard = (await import("../components/ActionApprovalCard")).default;
    render(<ActionApprovalCard kind="desktop_app" target="Notes" detail="" permKind="app" options={["task", "conversation", "always"]}
      alwaysLabel="Notes" onConfirm={() => {}} onCancel={() => {}} />);
    expect(conversationChoice("action-scope")).toHaveTextContent(/^In this conversation$/);
  });
});
