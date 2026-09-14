import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import copy from "../locales/connectorCatalog.json";
import { getMcpCatalog } from "../api/catalog";
import { addMcpServer, listMcpServers } from "../api/mcp";
import type { McpConnector } from "../api/client.types";
import RecommendedMcp from "../components/RecommendedMcp";
import ConnectMcpCard from "../components/ConnectMcpCard";

vi.mock("../api/catalog", () => ({ getMcpCatalog: vi.fn() }));
vi.mock("../api/mcp", () => ({ listMcpServers: vi.fn(), addMcpServer: vi.fn(), connectMcpServer: vi.fn(), exposeMcpServer: vi.fn(), wireMcpTool: vi.fn() }));
const connectors: McpConnector[] = Object.keys(copy.en).map(key => ({ key, label: key, description: `Source ${key}`,
  label_key: `catalogUI.connectors.${key}.name`, description_key: `catalogUI.connectors.${key}.description`,
  transport: "stdio", command: "npx", args: ["-y", `@example/${key}`], url: null, runtime: "node",
  auth: "none", one_click: true, env: [], requires_path: key === "filesystem" }));
const playwright: McpConnector = { ...connectors.find(c => c.key === "playwright")!, args: ["-y", "@playwright/mcp@0.0.80", "--isolated", "--sandbox"] };
beforeEach(() => {
  vi.mocked(getMcpCatalog).mockResolvedValue(connectors);
  vi.mocked(listMcpServers).mockResolvedValue([]);
});
afterEach(() => { cleanup(); vi.resetAllMocks(); void i18n.changeLanguage("en"); });

it.each(SUPPORTED_LANGUAGES)("renders every connector name and description in %s", async language => {
  await i18n.changeLanguage(language);
  render(<RecommendedMcp />);
  expect(await screen.findByText(copy[language].fetch.name)).toBeInTheDocument();
  for (const value of Object.values(copy[language])) {
    expect(screen.getByText(value.name)).toBeInTheDocument();
    expect(screen.getByText(value.description)).toBeInTheDocument();
  }
  expect(screen.getByRole("textbox")).toHaveAccessibleName(`${copy[language].filesystem.name} — ${i18n.t("connectionsUI.localPath")}`);
  expect(addMcpServer).not.toHaveBeenCalled();
});

it.each(SUPPORTED_LANGUAGES)("connect card translates metadata in %s without requesting a secret", async language => {
  await i18n.changeLanguage(language);
  render(<ConnectMcpCard callId="test" label="Source GitHub" labelKey="catalogUI.connectors.github.name"
    transport="stdio" command="npx" args={["-y", "@example/github"]} url={null}
    prerequisites="Needs: GITHUB_PERSONAL_ACCESS_TOKEN"
    envKeys={[{ name: "GITHUB_PERSONAL_ACCESS_TOKEN", description: "Source credential",
      description_key: "catalogUI.connectors.github.credentials.GITHUB_PERSONAL_ACCESS_TOKEN", get_it_url: "https://example.test/keys", paid: false }]}
    onApplied={vi.fn()} onCancel={vi.fn()} />);
  expect(screen.getByRole("heading", { name: copy[language].github.name })).toBeInTheDocument();
  expect(screen.getByText(copy[language].github.credentials.GITHUB_PERSONAL_ACCESS_TOKEN)).toBeInTheDocument();
  expect(screen.getByText(`${i18n.t('connectionsUI.needsKey')}: GITHUB_PERSONAL_ACCESS_TOKEN`)).toBeInTheDocument();
  expect(screen.getByLabelText("GITHUB_PERSONAL_ACCESS_TOKEN")).toHaveAttribute("type", "password");
  expect(addMcpServer).not.toHaveBeenCalled();
});

it.each([
  ["-y", "@other/package", "--sandbox"],
  ["-y", "@playwright/mcp@0.0.80", "--sandbox"],
  ["-y", "@playwright/mcp@0.0.79", "--isolated", "--sandbox"],
])("does not mistake an unrelated or less isolated command for the preset: %j", async (...args) => {
  vi.mocked(getMcpCatalog).mockResolvedValue([playwright]);
  vi.mocked(listMcpServers).mockResolvedValue([{ id: 1, label: "Synthetic", env: {}, status: "registered", command: "npx", args, transport: "stdio" }]);
  render(<RecommendedMcp />);
  expect(await screen.findByRole("button", { name: i18n.t("connectionsUI.connect") })).toBeInTheDocument();
  expect(screen.queryByText(i18n.t("connectionsUI.added"))).not.toBeInTheDocument();
});

it("recognizes the complete pinned private-browser preset", async () => {
  vi.mocked(getMcpCatalog).mockResolvedValue([playwright]);
  vi.mocked(listMcpServers).mockResolvedValue([{ id: 1, label: "Synthetic", env: {}, status: "registered", command: "npx", args: playwright.args, transport: "stdio" }]);
  render(<RecommendedMcp />);
  expect(await screen.findByText(i18n.t("connectionsUI.added"))).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: i18n.t("connectionsUI.connect") })).not.toBeInTheDocument();
});

it("path errors update with the selected language", async () => {
  await i18n.changeLanguage("en");
  vi.mocked(getMcpCatalog).mockResolvedValue([connectors.find(c => c.key === "filesystem")!]);
  render(<RecommendedMcp />);
  const button = await screen.findByRole("button", { name: i18n.t("connectionsUI.connect") });
  fireEvent.click(button);
  expect(screen.getByText(i18n.t("connectionsUI.pathFirst"))).toBeInTheDocument();
  await act(async () => { await i18n.changeLanguage("zh"); });
  expect(screen.getByText(i18n.t("connectionsUI.pathFirst"))).toBeInTheDocument();
  expect(addMcpServer).not.toHaveBeenCalled();
});

it("shows a localized fetch failure and retries only the read", async () => {
  await i18n.changeLanguage("fr");
  vi.mocked(getMcpCatalog).mockRejectedValueOnce(new Error("synthetic offline"));
  render(<RecommendedMcp />);
  const alert = await screen.findByRole("alert");
  expect(within(alert).getByText(i18n.t("create_card.picker.error"))).toBeInTheDocument();
  fireEvent.click(within(alert).getByRole("button", { name: i18n.t("connectionsUI.refreshList") }));
  expect(await screen.findByText(copy.fr.fetch.name)).toBeInTheDocument();
  expect(addMcpServer).not.toHaveBeenCalled();
});
