import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SpawnDetail from "../components/SpawnDetail";

vi.mock("../api/client", () => ({
  api: {
    getKnowledge: vi.fn(),
    ingestKnowledgeText: vi.fn(),
    ingestKnowledgeFile: vi.fn(),
    ingestKnowledgeUrl: vi.fn(),
    deleteKnowledge: vi.fn(),
    evolveSpawn: vi.fn(),
    confirmProposal: vi.fn(),
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

  it("proposes evolution and shows the gate verdict", async () => {
    m.evolveSpawn.mockResolvedValue({
      proposal_id: 11, candidate_prompt: "improved prompt",
      gate: { passed: true, reason: "improves without regression",
              aggregate: { overall: { better: 2, worse: 0, tie: 1 } } },
      evidence: {},
    });
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");
    fireEvent.click(screen.getByText("提出进化提案"));
    await screen.findByText(/通过/);
    expect(screen.getByText("采纳")).toBeTruthy();
  });

  it("confirms a passed proposal", async () => {
    m.evolveSpawn.mockResolvedValue({
      proposal_id: 11, candidate_prompt: "p",
      gate: { passed: true, reason: "ok", aggregate: null }, evidence: {},
    });
    m.confirmProposal.mockResolvedValue({ ok: true, spawn_id: 7, generation_level: 2 });
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");
    fireEvent.click(screen.getByText("提出进化提案"));
    await screen.findByText("采纳");
    fireEvent.click(screen.getByText("采纳"));
    await screen.findByText(/已采纳/);
  });

  it("hides 采纳 when the gate failed", async () => {
    m.evolveSpawn.mockResolvedValue({
      proposal_id: null, candidate_prompt: null,
      gate: { passed: false, reason: "no scored runs", aggregate: null }, evidence: null,
    });
    render(<SpawnDetail spawnId={7} spawnName="小美" onClose={() => {}} />);
    await screen.findByText("policy.txt");
    fireEvent.click(screen.getByText("提出进化提案"));
    await screen.findByText(/no scored runs|可评估/);
    expect(screen.queryByText("采纳")).toBeNull();
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
