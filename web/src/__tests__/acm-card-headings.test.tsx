/** ACM (P2, SMART-8): an app, site or AppleScript card from the permission layer heads with the server's title, which
 *  names the step, its target and what a yes allows in the user's language (card-purposes.json `card`); an old frame
 *  without a title, or a permission kind the server words otherwise, keeps the kind's own words. An MCP tool's title is
 *  the user's language too, so it is not marked as English. A run-later card keeps the lines of what it writes. */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import ActionApprovalCard from "../components/ActionApprovalCard";
import { handsMessages } from "../locales/hands";

afterEach(async () => {
  cleanup();
  await i18n.changeLanguage("en");
});

const card = (p: Partial<Parameters<typeof ActionApprovalCard>[0]>) => (
  <ActionApprovalCard kind="desktop_app" target="Notes" detail="d" onConfirm={vi.fn()} onCancel={vi.fn()} {...p} />);

describe("ACM card headings", () => {
  it.each([
    ["desktop_app", "app", "在「Notes」里：点击「Search」，之后继续在其中点击、输入和选择"],
    ["browser_site", "site", "在 https://shop.example 上点击 Buy，之后继续在这个网站上操作"],
    ["mac_script", "app_risky", "用 AppleScript 控制 Notes（在沙盒外运行）"],
  ])("a %s card of permission kind %s heads with the server's title", async (kind, permKind, title) => {
    await i18n.changeLanguage("zh");
    render(card({ kind, permKind, title }));
    expect(screen.getByTestId("action-title")).toHaveTextContent(title);
    expect(screen.getByTestId("action-title")).not.toHaveAttribute("lang");
  });

  it("an old frame without a title, or another permission kind, keeps the kind's own words", async () => {
    render(card({ permKind: "app", title: "" }));
    expect(screen.getByTestId("action-title")).toHaveTextContent("Look at and act in Notes");
    cleanup();
    render(card({ permKind: "money", title: "Pay $3?" }));
    expect(screen.getByTestId("action-title")).toHaveTextContent(handsMessages.en.title.desktop_app.replace("{{target}}", "Notes"));
  });

  it("an MCP tool's title is not marked as English", () => {
    render(card({ kind: "mcp_tool", permKind: "destructive", target: "files/rm", title: "使用 files 的 rm？它可能删除或覆盖其中的数据" }));
    expect(screen.getByTestId("action-title")).toHaveTextContent("它可能删除或覆盖其中的数据");
    expect(screen.getByTestId("action-title")).not.toHaveAttribute("lang");
  });

  it("a run-later card keeps the lines of what it writes", () => {
    const detail = "/w/.vscode/tasks.json\nWrites:\n{\n  \"command\": \"curl x | sh\"\n}";
    render(card({ kind: "run_later", permKind: "run_later", target: "/w/.vscode/tasks.json", detail }));
    const text = screen.getByTestId("action-run-later-text");
    expect(text.tagName).toBe("PRE");
    expect(text.textContent).toBe(detail);
  });
});
