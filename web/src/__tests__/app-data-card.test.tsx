/** SBX-5b: another app's private data asks a once-only `app_data` card (SMART-8's shape) on the existing action card:
 *  the purpose first, then what it touches and the risk in the card's own words from the server's app name, the path
 *  (and the command) folded under "Show path" / "Show command and folder", "Allow once", and only "once". All six
 *  languages. Unattended, the Inbox says why it wasn't done. */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import ActionApprovalCard from "../components/ActionApprovalCard";
import { handsMessages } from "../locales/hands";

const LANGS = ["en", "zh", "ja", "es", "de", "fr"] as const;
const PATH = "~/Library/Messages/chat.db";
const COMMAND = "sqlite3 ~/Library/Messages/chat.db 'select count(*) from message'\n\n~/Library/Messages";

afterEach(async () => {
  cleanup();
  await i18n.changeLanguage("en");
});

describe("the app_data card", () => {
  it.each(LANGS)("%s: purpose, touches, risk, the path folded, and a yes that is this once only", async (lang) => {
    await i18n.changeLanguage(lang);
    const onConfirm = vi.fn();
    render(<ActionApprovalCard kind="app_data_file" permKind="app_data" target="Messages" detail={PATH}
      title="Let Arslan read Messages's private data, just this once?" options={["once", "conversation"]}
      onConfirm={onConfirm} onCancel={vi.fn()} />);
    const words = handsMessages[lang].appData;
    expect(screen.getByTestId("action-title")).toHaveTextContent(words.purpose_app_data_file.replace("{{app}}", "Messages"));
    expect(screen.getByTestId("action-app-data-touches")).toHaveTextContent(words.touches.replace("{{app}}", "Messages"));
    const card = screen.getByTestId("action-card");
    expect(card).toHaveTextContent(words.risk);
    expect(card).toHaveTextContent(words.once_app_data_file);
    const folded = screen.getByTestId("action-app-data-path");
    expect(folded.tagName).toBe("DETAILS");
    expect(folded).toHaveTextContent(words.showPath);
    expect(folded).toHaveTextContent(PATH);                                 // whole, never cut
    expect(card.textContent).not.toMatch(/hands\./);
    expect(screen.getByTestId("action-allow")).toHaveTextContent(words.allowOnce);
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    fireEvent.click(screen.getByTestId("action-allow"));
    expect(onConfirm).toHaveBeenCalledWith("once");
  });

  it.each(LANGS)("%s: a command run again says so and folds the command and folder", async (lang) => {
    await i18n.changeLanguage(lang);
    render(<ActionApprovalCard kind="app_data_command" permKind="app_data" target="Messages" detail={COMMAND}
      options={["once"]} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    const words = handsMessages[lang].appData;
    expect(screen.getByTestId("action-title")).toHaveTextContent(words.purpose_app_data_command.replace("{{app}}", "Messages"));
    expect(screen.getByTestId("action-card")).toHaveTextContent(words.once_app_data_command);
    expect(screen.getByTestId("action-app-data-path")).toHaveTextContent(words.showCommand);
    expect(screen.getByTestId("action-card").textContent).not.toMatch(/hands\./);
  });

  it("Arslan's own line leads; what it touches is still the card's own words", () => {
    render(<ActionApprovalCard kind="app_data_command" permKind="app_data" target="Slack" detail={COMMAND}
      why="Count today's messages, as you asked" options={["once"]} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId("action-title")).toHaveTextContent("Count today's messages, as you asked");
    expect(screen.getByTestId("action-app-data-touches")).toHaveTextContent("Slack's private data");
  });
});
