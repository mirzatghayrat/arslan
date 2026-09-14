import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import { connectionMessages } from "../locales/connections";
import McpServers from "../components/McpServers";

vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn(async () => []),
  addMcpServer: vi.fn(), connectMcpServer: vi.fn(), deleteMcpServer: vi.fn(),
  exposeMcpServer: vi.fn(), listMcpTools: vi.fn(), reconnectMcpServer: vi.fn(),
  setMcpServerHost: vi.fn(), wireMcpTool: vi.fn(), authorizeMcpOauth: vi.fn(),
  getMcpOauthStatus: vi.fn(),
}));
vi.mock("../lib/shell", () => ({ openExternal: vi.fn() }));
afterEach(() => { cleanup(); void i18n.changeLanguage("en"); });

describe("connection language coverage", () => {
  it.each(SUPPORTED_LANGUAGES)("renders translated controls and accessible names in %s", async language => {
    await i18n.changeLanguage(language);
    render(<McpServers />);
    const messages = connectionMessages[language];
    expect(screen.getByRole("heading", { name: messages.servers })).toBeTruthy();
    expect(screen.getByText(messages.none)).toBeTruthy();
    expect(screen.getByRole("textbox", { name: messages.label })).toBeTruthy();
    expect(screen.getByRole("combobox", { name: messages.transport })).toBeTruthy();
    expect(screen.getByRole("button", { name: messages.addServer })).toBeTruthy();
    expect(screen.getByRole("button", { name: messages.removeRow })).toBeTruthy();
    expect(document.body.textContent).not.toContain("connectionsUI.");
  });

  it("keeps all keys and interpolation variables in every language", () => {
    const tokens = (value: string) => value.match(/\{\{[^}]+\}\}/g)?.sort() ?? [];
    for (const language of SUPPORTED_LANGUAGES) {
      const messages = connectionMessages[language];
      expect(Object.keys(messages).sort()).toEqual(Object.keys(connectionMessages.en).sort());
      for (const key of Object.keys(connectionMessages.en) as Array<keyof typeof connectionMessages.en>) {
        expect(messages[key].trim()).not.toBe("");
        expect(tokens(messages[key])).toEqual(tokens(connectionMessages.en[key]));
      }
    }
  });
});
