import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import i18n, { SUPPORTED_LANGUAGES } from "../i18n";
import { designMessages } from "../locales/design";
import { request } from "../api/client";
import ConnectionsSection from "../components/companion/ConnectionsSection";

vi.mock("../api/client", () => ({ request: vi.fn() }));
vi.mock("../components/McpServers", () => ({ default: () => null }));
vi.mock("../components/RecommendedMcp", () => ({ default: () => null }));
vi.mock("../components/settings/ToolTransportWarning", () => ({ default: () => null }));
beforeEach(() => {
  vi.mocked(request).mockImplementation(async path => path.includes("local-media")
    ? { local: { generate: false, edit: false }, blocked_reason: "media_host_setup_required" }
    : { local: { read_account: false, write_draft: false, submit_review: false, publish: false } } as never);
});
afterEach(() => { cleanup(); vi.resetAllMocks(); void i18n.changeLanguage("en"); });

it.each(SUPPORTED_LANGUAGES)("discloses unavailable generation in %s without an enable action", async language => {
  await i18n.changeLanguage(language);
  render(<ConnectionsSection onOpenSettings={vi.fn()} />);
  expect(await screen.findByText(designMessages[language].mediaUnavailable)).toBeInTheDocument();
  expect(screen.getByText(designMessages[language].mediaFallback)).toBeInTheDocument();
  const section = screen.getByRole("heading", { name: designMessages[language].mediaTitle }).closest("section");
  expect(section?.querySelector("button,input,a")).toBeNull();
  expect(request).toHaveBeenCalledWith("/connections/local-media/capabilities");
});

it("does not infer backend absence when status cannot be checked", async () => {
  vi.mocked(request).mockRejectedValue(new Error("offline"));
  render(<ConnectionsSection onOpenSettings={vi.fn()} />);
  await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  expect(screen.queryByText(designMessages.en.mediaUnavailable)).not.toBeInTheDocument();
  expect(screen.getAllByText(i18n.t("workspace.connectionStatusUnknown"))).toHaveLength(2);
});
