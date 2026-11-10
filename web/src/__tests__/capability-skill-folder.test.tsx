/** v0.1.64 CAP6a: a skill from ~/.agents/skills. Another tool's shows "from another tool" with a switch and no
 *  delete; switching it on shows its card first (the server answers 409 needs_card), which says the folder is
 *  shared, and a yes approves exactly the files shown. The install card says the folder is shared too. */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, act } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, o?: Record<string, unknown>) => (o && "count" in o ? `${key}:${o.count}` : key) }),
}));
vi.mock("../api/mcp", () => ({
  listMcpServers: vi.fn().mockResolvedValue([]), listMcpTools: vi.fn().mockResolvedValue([]),
}));

import CapabilitySwitches from "../components/CapabilitySwitches";
import AskSlot from "../components/AskSlot";
import { capabilitiesApi, type CapabilityRow, type SkillFolderCard } from "../api/capabilities";
import { ApiError } from "../api/client";
import { capabilityListMessages } from "../locales/capabilityList";
import { useArslanStore, initialArslanState } from "../stores/arslanStore";

const OTHER: CapabilityRow = { key: "skill:pdf-notes", section: "skills", origin: "other_tool", deletable: false,
  last_used: null, source_id: null, reach: null, state: "off", tools: [], switch: "skill", reason: "skill_needs_card",
  fix: null, name: "pdf-notes", detail: "Take notes from a PDF." };
const CARD: SkillFolderCard = { kind: "skill_folder", key: "pdf-notes", name: "pdf-notes", description: "Take notes from a PDF.",
  origin: "other_tool", changed: false, folder: "~/.agents/skills/pdf-notes", skill_md: "---\nname: pdf-notes\n---\n## Trigger\nx\n",
  hidden: { count: 0, runs: [], more: 0 }, files: ["SKILL.md", "scripts/count.py"], unscanned: [], digest: "d1",
  shared_folder: true, scan: { level: "clean", findings: [] } };

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("a skill from ~/.agents/skills", () => {
  it("another tool's: from another tool, a switch, no delete, and why it is off", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue([OTHER]);
    render(<CapabilitySwitches />);
    const line = await screen.findByTestId("cap-skill:pdf-notes");
    expect(line).toHaveTextContent("capabilityList.origin_other_tool");
    expect(screen.getByTestId("cap-switch-skill:pdf-notes")).not.toBeChecked();
    expect(screen.queryByTestId("cap-delete-skill:pdf-notes")).toBeNull();
    expect(screen.getByTestId("cap-reason-skill:pdf-notes")).toHaveTextContent("capabilityList.reason_skill_needs_card");
  });

  it("switching it on shows the card, which says the folder is shared; a yes approves the files shown", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue([OTHER]);
    vi.spyOn(capabilitiesApi, "switch").mockRejectedValue(new ApiError("needs_card", 409, { code: "needs_card", card: CARD }));
    const approve = vi.spyOn(capabilitiesApi, "approveSkillFolder").mockResolvedValue({ ...OTHER, state: "on", reason: null });
    render(<CapabilitySwitches />);
    fireEvent.click(await screen.findByTestId("cap-switch-skill:pdf-notes"));
    const card = await screen.findByTestId("skill-folder-card");
    expect(card).toHaveTextContent("capabilityList.origin_other_tool");
    expect(screen.getByTestId("skill-folder-shared")).toHaveTextContent("capabilityList.sharedFolder");
    expect(screen.getByTestId("skill-folder-body")).toHaveTextContent("## Trigger");
    expect(screen.getByTestId("skill-folder-files")).toHaveTextContent("scripts/count.py");
    fireEvent.click(screen.getByTestId("skill-folder-allow"));
    await waitFor(() => expect(approve).toHaveBeenCalledWith("pdf-notes", "d1"));
    await waitFor(() => expect(screen.queryByTestId("skill-folder-card")).toBeNull());
    expect(screen.getByTestId("cap-switch-skill:pdf-notes")).toBeChecked();
  });

  it("a blocked scan can't be approved, and says what it found first", async () => {
    vi.spyOn(capabilitiesApi, "list").mockResolvedValue([OTHER]);
    const blocked = { ...CARD, scan: { level: "blocked" as const, findings: [{ rule: "pipe_to_shell", level: "high", file: "SKILL.md", line: 3, excerpt: "" }] } };
    vi.spyOn(capabilitiesApi, "switch").mockRejectedValue(new ApiError("needs_card", 409, { code: "needs_card", card: blocked }));
    render(<CapabilitySwitches />);
    fireEvent.click(await screen.findByTestId("cap-switch-skill:pdf-notes"));
    expect(await screen.findByTestId("skill-folder-findings")).toHaveTextContent("capabilityList.folderCard_findings");
    expect(screen.getByTestId("skill-folder-allow")).toBeDisabled();
  });

  it("the shared-folder line is in every language", () => {
    for (const messages of Object.values(capabilityListMessages)) {
      expect((messages as Record<string, string>).sharedFolder).toContain("~/.agents/skills");
    }
  });

  it("the install card says the folder is shared", () => {
    useArslanStore.setState(initialArslanState(), true);
    render(<AskSlot send={() => {}} />);
    act(() => { useArslanStore.getState().handleFrame({ type: "propose_capability", call_id: "cap-1", kind: "skill",
      name: "Weekly report", summary: "", source_url: null, repo: "acme/skills", version: null,
      license: { spdx: "MIT", read_from: null }, stars: null, pushed_days: null, runtime: "skill", runtime_download: null,
      remote_host: null, network: false, folders: [], keys: [], why: "", retry: "", shared_folder: true } as never); });
    expect(screen.getByTestId("capability-card-shared")).toHaveTextContent("capabilityList.sharedFolder");
  });
});
