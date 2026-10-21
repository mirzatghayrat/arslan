/** S1: an MCP tool's card in the window starts on "In this conversation" (a tool is usually used again in the
 *  same conversation); a destructive one offers this time only; other kinds keep their narrowest start. Only the
 *  window's starting choice changes: the options' order is the server's, and the island and the phone still
 *  answer the first ("this time"). */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import ActionApprovalCard from "../components/ActionApprovalCard";

afterEach(() => { cleanup(); });

function allow(permKind: string, options: string[], alwaysLabel?: string) {
  const onConfirm = vi.fn();
  render(<ActionApprovalCard kind="mcp_tool" target="files/write_file" detail='{"path": "/a"}' permKind={permKind}
    options={options} alwaysLabel={alwaysLabel} onConfirm={onConfirm} onCancel={vi.fn()} />);
  fireEvent.click(screen.getByTestId("action-allow"));
  return onConfirm.mock.calls[0][0];
}

describe("S1: the MCP card's starting choice", () => {
  it("an MCP tool's yes is for this conversation unless the person picks this time", async () => {
    await i18n.changeLanguage("en");
    expect(allow("mcp_tool", ["once", "conversation"])).toBe("conversation");
  });

  it("a destructive tool's yes is for this time only", async () => {
    await i18n.changeLanguage("en");
    expect(allow("destructive", ["once"])).toBe("once");
  });

  it("its 'In this conversation' says it covers any use of the tool, with any arguments (⓪Plan's review)", async () => {
    await i18n.changeLanguage("en");
    render(<ActionApprovalCard kind="mcp_tool" target="files/write_file" detail='{"path": "/a"}' permKind="mcp_tool"
      options={["once", "conversation"]} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId("action-scope-conversation").parentElement).toHaveTextContent(
      String(i18n.t("kit.scope.conversationFor", { label: String(i18n.t("kit.scope.anyToolUse")) })));
  });

  it("other kinds still start on their narrowest choice", async () => {
    await i18n.changeLanguage("en");
    expect(allow("app", ["task", "conversation", "always"], "Notes")).toBe("task");
  });
});
