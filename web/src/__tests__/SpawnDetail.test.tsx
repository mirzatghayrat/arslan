import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SpawnDetail from "../components/SpawnDetail";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock("../api/client", () => ({
  api: {
    getKnowledge: vi.fn(),
    getPreferences: vi.fn().mockResolvedValue({ preferences: [] }),
    deletePreference: vi.fn(),
    ingestKnowledgeText: vi.fn(),
    ingestKnowledgeFile: vi.fn(),
    ingestKnowledgeUrl: vi.fn(),
    deleteKnowledge: vi.fn(),
    getEvolveEstimate: vi.fn(),
    runEvolve: vi.fn(),
  },
}));
import { api } from "../api/client";

const m = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  m.getKnowledge.mockResolvedValue([{ source: "policy.txt", chunks: 4 }]);
});

describe("SpawnDetail", () => {
  it("lists knowledge sources on mount", async () => {
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");
    expect(screen.getByText(/4/)).toBeTruthy();
  });

  it("adds text knowledge and refreshes", async () => {
    m.ingestKnowledgeText.mockResolvedValue({ source: "note", chunks_added: 2 });
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");

    fireEvent.change(screen.getByPlaceholderText(/标签|source/i), { target: { value: "note" } });
    fireEvent.change(screen.getByPlaceholderText(/粘贴|文本|text/i), { target: { value: "some material" } });
    fireEvent.click(screen.getByText("添加文本"));

    await waitFor(() => expect(m.ingestKnowledgeText).toHaveBeenCalledWith(7, "note", "some material", false));
    expect(m.getKnowledge).toHaveBeenCalledTimes(2);
  });

  it("shows the cost estimate before enqueuing evolution", async () => {
    m.getEvolveEstimate.mockResolvedValue({
      pairs: 12, dispatches: 156, judge_calls: 24, optimizer_calls: 3,
      synth_calls: 0, est_tokens: 48000, lower_bound: true,
    });
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");
    fireEvent.click(screen.getByText("evolution.inbox.estimate_title"));
    await waitFor(() => expect(m.getEvolveEstimate).toHaveBeenCalledWith(7));
    // The enqueue button only appears once the estimate is shown.
    await screen.findByText("evolution.inbox.enqueue");
  });

  it("enqueues a background evolution attempt", async () => {
    m.getEvolveEstimate.mockResolvedValue({
      pairs: 12, dispatches: 156, judge_calls: 24, optimizer_calls: 3,
      synth_calls: 0, est_tokens: 48000, lower_bound: true,
    });
    m.runEvolve.mockResolvedValue({ attempt_id: 99 });
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");
    fireEvent.click(screen.getByText("evolution.inbox.estimate_title"));
    fireEvent.click(await screen.findByText("evolution.inbox.enqueue"));
    await waitFor(() => expect(m.runEvolve).toHaveBeenCalledWith(7));
    await screen.findByText("evolution.inbox.enqueued");
  });

  it("ingests a URL and refreshes", async () => {
    m.ingestKnowledgeUrl.mockResolvedValue({ source: "https://x.com", chunks_added: 2 });
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");
    fireEvent.change(screen.getByPlaceholderText(/网址|url|http/i), { target: { value: "https://x.com" } });
    fireEvent.click(screen.getByText("抓取"));
    await waitFor(() => expect(m.ingestKnowledgeUrl).toHaveBeenCalledWith(7, "https://x.com", false));
  });
});
