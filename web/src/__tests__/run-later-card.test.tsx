/** HR-2a: a file tool's write into a file that runs later asks a once-only `run_later` card. The existing action card
 *  shows it with words of its own in all six languages (a kind mapping and strings, no new layout): its title, the path
 *  as the detail, the sentence that says what such a file is and that this allows one write, and only "once". */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import ActionApprovalCard from "../components/ActionApprovalCard";
import { handsMessages } from "../locales/hands";

const LANGS = ["en", "zh", "ja", "es", "de", "fr"] as const;
const PATH = "/work/project/.vscode/tasks.json";

afterEach(async () => {
  cleanup();
  await i18n.changeLanguage("en");
});

describe("the run_later card", () => {
  it.each(LANGS)("%s: its own title and line, the path, and a yes that is this once only", async (lang) => {
    await i18n.changeLanguage(lang);
    const onConfirm = vi.fn();
    render(<ActionApprovalCard kind="run_later" permKind="run_later" target={PATH} detail={PATH}
      title="Write tasks.json? Another program runs it or loads it as settings later."
      options={["once", "conversation"]} onConfirm={onConfirm} onCancel={vi.fn()} />);
    const words = handsMessages[lang];
    expect(words.title.run_later).toBeTruthy();
    expect(words.scope.run_later).toBeTruthy();
    expect(screen.getByTestId("action-title")).toHaveTextContent(words.title.run_later);
    const card = screen.getByTestId("action-card");
    expect(card).toHaveTextContent(PATH);
    expect(card).toHaveTextContent(words.scope.run_later);
    expect(card.textContent).not.toMatch(/hands\./);
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
    fireEvent.click(screen.getByTestId("action-allow"));
    expect(onConfirm).toHaveBeenCalledWith("once");
  });
});
