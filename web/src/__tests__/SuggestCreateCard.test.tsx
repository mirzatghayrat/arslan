import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// ── i18n mock: t returns the key so assertions are language-independent ──────────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
    i18n: { changeLanguage: vi.fn() },
  }),
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

// ── api mock ────────────────────────────────────────────────────────────────────
vi.mock("../api/client", () => ({ api: { getRegistry: vi.fn() } }));
import { api } from "../api/client";
const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

import SuggestCreateCard from "../components/SuggestCreateCard";
import type { SuggestDraft, OverlapInfo } from "../api/client.types";

const fullDraft: SuggestDraft = {
  name: "Researcher",
  domain: "research",
  capabilities: ["search", "summarize"],
  persona_role: "analyst",
  persona_tone: "concise",
  reason: "needs web research",
  tools: ["web_search"],
  skills: ["deep-research"],
  mcps: ["mcp_github"],
  gaps: ["no notion access"],
  seed_refs: ["agency-agents:researcher", "agency-agents:analyst"],
};

beforeEach(() => {
  vi.clearAllMocks();
  m.getRegistry.mockResolvedValue({
    toolsets: [
      { key: "web_extract", name: "Web Extract", description: "d", tier: "safe", status: "wired", assignable: true, tools: [] },
      { key: "mcp_notion", name: "Notion", description: "d", tier: "safe", status: "wired", assignable: true, tools: [] },
    ],
    skills: [
      { key: "humanizer", name: "Humanizer", category: "writing", description: "d", tier: "safe", status: "registered", assignable: true },
    ],
  });
});

describe("SuggestCreateCard (editable config card)", () => {
  it("renders the three equipment rows with their chips", () => {
    render(
      <SuggestCreateCard
        draft={fullDraft}
        taskBrief="research the market"
        overlaps={null}
        onCreate={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByTestId("chip-tool-web_search")).toBeInTheDocument();
    expect(screen.getByTestId("chip-skill-deep-research")).toBeInTheDocument();
    expect(screen.getByTestId("chip-mcp-mcp_github")).toBeInTheDocument();
  });

  it("sends equipment on create: toolsets = tools + mcps, skills separate", () => {
    const onCreate = vi.fn();
    render(
      <SuggestCreateCard
        draft={fullDraft}
        taskBrief="research the market"
        overlaps={null}
        onCreate={onCreate}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("btn-create"));
    expect(onCreate).toHaveBeenCalledOnce();
    const sent = onCreate.mock.calls[0][0] as SuggestDraft & {
      equipment: { toolsets: string[]; skills: string[] };
    };
    expect(sent.equipment.toolsets).toEqual(["web_search", "mcp_github"]);
    expect(sent.equipment.skills).toEqual(["deep-research"]);
  });

  it("removing a chip drops it from what gets sent", () => {
    const onCreate = vi.fn();
    render(
      <SuggestCreateCard
        draft={fullDraft}
        taskBrief={null}
        overlaps={null}
        onCreate={onCreate}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("remove-tool-web_search"));
    expect(screen.queryByTestId("chip-tool-web_search")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("btn-create"));
    const sent = onCreate.mock.calls[0][0] as { equipment: { toolsets: string[] } };
    expect(sent.equipment.toolsets).toEqual(["mcp_github"]);
  });

  it("renders gaps with the three action buttons and calls onFillGap", () => {
    const onFillGap = vi.fn();
    render(
      <SuggestCreateCard
        draft={fullDraft}
        taskBrief={null}
        overlaps={null}
        onCreate={vi.fn()}
        onDismiss={vi.fn()}
        onFillGap={onFillGap}
      />,
    );
    expect(screen.getByText("no notion access")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("gap-discover-mcp-0"));
    fireEvent.click(screen.getByTestId("gap-distill-skill-0"));
    fireEvent.click(screen.getByTestId("gap-request-grant-0"));
    expect(onFillGap).toHaveBeenCalledWith("discover_mcp", "no notion access");
    expect(onFillGap).toHaveBeenCalledWith("distill_skill", "no notion access");
    expect(onFillGap).toHaveBeenCalledWith("request_grant", "no notion access");
  });

  it("renders seed provenance with the slugs", () => {
    render(
      <SuggestCreateCard
        draft={fullDraft}
        taskBrief={null}
        overlaps={null}
        onCreate={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    const prov = screen.getByTestId("seed-provenance");
    expect(prov.textContent).toContain("agency-agents:researcher");
    expect(prov.textContent).toContain("agency-agents:analyst");
  });

  it("editing the name flows into the created draft", () => {
    const onCreate = vi.fn();
    render(
      <SuggestCreateCard
        draft={fullDraft}
        taskBrief={null}
        overlaps={null}
        onCreate={onCreate}
        onDismiss={vi.fn()}
      />,
    );
    const nameInput = screen.getByTestId("edit-name") as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: "MarketBot" } });
    fireEvent.click(screen.getByTestId("btn-create"));
    const sent = onCreate.mock.calls[0][0] as SuggestDraft;
    expect(sent.name).toBe("MarketBot");
  });

  it("carries the edited brief out on create (regression)", () => {
    const onCreate = vi.fn();
    render(
      <SuggestCreateCard
        draft={fullDraft}
        taskBrief="research the market"
        overlaps={null}
        onCreate={onCreate}
        onDismiss={vi.fn()}
      />,
    );
    const briefInput = screen.getByTestId("edit-brief") as HTMLTextAreaElement;
    fireEvent.change(briefInput, { target: { value: "research EV chargers in the EU" } });
    fireEvent.click(screen.getByTestId("btn-create"));
    const sent = onCreate.mock.calls[0][0] as { brief: string };
    // The edited brief — not the original taskBrief — must reach the payload.
    expect(sent.brief).toBe("research EV chargers in the EU");
  });

  it("adds a tool from the registry picker", async () => {
    const onCreate = vi.fn();
    render(
      <SuggestCreateCard
        draft={fullDraft}
        taskBrief={null}
        overlaps={null}
        onCreate={onCreate}
        onDismiss={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("add-tool"));
    await waitFor(() => screen.getByTestId("pick-tool-web_extract"));
    fireEvent.click(screen.getByTestId("pick-tool-web_extract"));
    expect(screen.getByTestId("chip-tool-web_extract")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("btn-create"));
    const sent = onCreate.mock.calls[0][0] as { equipment: { toolsets: string[] } };
    expect(sent.equipment.toolsets).toContain("web_extract");
  });

  it("calls onDismiss when 忽略 is clicked", () => {
    const onDismiss = vi.fn();
    render(
      <SuggestCreateCard
        draft={fullDraft}
        taskBrief={null}
        overlaps={null}
        onCreate={vi.fn()}
        onDismiss={onDismiss}
      />,
    );
    fireEvent.click(screen.getByTestId("btn-dismiss"));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("calls onRefine when 继续聊改 is clicked", () => {
    const onRefine = vi.fn();
    render(
      <SuggestCreateCard
        draft={fullDraft}
        taskBrief={null}
        overlaps={null}
        onCreate={vi.fn()}
        onDismiss={vi.fn()}
        onRefine={onRefine}
      />,
    );
    fireEvent.click(screen.getByTestId("btn-refine"));
    expect(onRefine).toHaveBeenCalledOnce();
  });

  it("still shows the overlap warning", () => {
    const overlaps: OverlapInfo = { spawn_id: 42, name: "DataAnalyst", axes: ["stats"] };
    render(
      <SuggestCreateCard
        draft={fullDraft}
        taskBrief={null}
        overlaps={overlaps}
        onCreate={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    const warning = screen.getByTestId("overlap-warning");
    expect(warning.textContent).toContain("DataAnalyst");
  });
});
