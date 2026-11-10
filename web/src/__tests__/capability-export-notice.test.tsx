/** CAP6a part 2: after the one-time export, the Capabilities page tells the user once, in one line, that their
 *  imported skills now live in ~/.agents/skills, where other tools can use them. Shown once: "seen" is recorded as
 *  soon as it shows. Nothing exported, or already seen: no line. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o && "count" in o ? `${key}:${o.count}` : key) }),
}));
vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn().mockResolvedValue([]), listMcpTools: vi.fn().mockResolvedValue([]),
}));

import CapabilitySwitches from "../components/CapabilitySwitches";
import { capabilitiesApi } from "../api/capabilities";
import { capabilityListMessages } from "../locales/capabilityList";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("the export's one line", () => {
  it("shows how many skills moved, once, and records that it showed", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue([]);
    vi.spyOn(capabilitiesApi, "exportNotice").mockResolvedValue({ count: 3 });
    const seen = vi.spyOn(capabilitiesApi, "exportNoticeSeen").mockResolvedValue({ ok: true });
    render(<CapabilitySwitches />);
    expect(await screen.findByTestId("cap-export-notice")).toHaveTextContent("capabilityList.exportedNotice:3");
    await waitFor(() => expect(seen).toHaveBeenCalledTimes(1));
  });

  it("shows nothing, and records nothing, when nothing moved or it was already shown", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue([]);
    const notice = vi.spyOn(capabilitiesApi, "exportNotice").mockResolvedValue({ count: 0 });
    const seen = vi.spyOn(capabilitiesApi, "exportNoticeSeen").mockResolvedValue({ ok: true });
    render(<CapabilitySwitches />);
    await waitFor(() => expect(notice).toHaveBeenCalled());
    await screen.findByText("capabilityList.tab");
    expect(screen.queryByTestId("cap-export-notice")).toBeNull();
    expect(seen).not.toHaveBeenCalled();
  });

  it("has the line in every language, naming the shared folder", () => {
    for (const [language, messages] of Object.entries(capabilityListMessages)) {
      for (const key of ["exportedNotice_one", "exportedNotice_other"] as const) {
        expect(messages[key], `${language} ${key}`).toContain("~/.agents/skills");
      }
      expect(messages.exportedNotice_other, language).toContain("{{count}}");
    }
  });
});
