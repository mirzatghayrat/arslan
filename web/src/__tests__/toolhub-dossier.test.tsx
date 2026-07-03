import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

vi.mock('../api/discovery', () => ({
  evaluateRepo: vi.fn(),
  searchRepos: vi.fn(),
  saveCandidate: vi.fn(),
  scanSkills: vi.fn(),
  importSkill: vi.fn(),
  generateSkill: vi.fn(),
  createSkill: vi.fn(),
}));

vi.mock('../api/mcp', () => ({
  addMcpServer: vi.fn(),
}));

vi.mock('../api/client', () => ({
  api: {
    listSpawns: vi.fn(),
    ingestKnowledgeText: vi.fn(),
  },
}));

import * as discovery from '../api/discovery';
import { addMcpServer } from '../api/mcp';
import { api } from '../api/client';
import type { EvalResult } from '../api/discovery';
import ToolHubDiscover from '../components/ToolHubDiscover';
import RepoDossier, { isLicensePermissive, detectRepoKind } from '../components/RepoDossier';

const EVAL: EvalResult = {
  repo: {
    full_name: 'owner/repo',
    html_url: 'https://github.com/owner/repo',
    stars: 1234,
    forks: 56,
    license: 'MIT',
    pushed_days: 3,
    description: 'A test MCP server for things.',
    topics: ['mcp', 'ai'],
  },
  trust: { tier: 'high', license_note: 'MIT — permissive.' },
  suggestion: {
    is_mcp: true,
    transport: 'stdio',
    command: 'npx',
    args: ['-y', '@owner/repo'],
    url: null,
    reason: 'Adds a useful capability for Arslan.',
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  (api.listSpawns as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

describe('ToolHub hero', () => {
  it('repo-shaped input calls the eval endpoint and renders the dossier', async () => {
    (discovery.evaluateRepo as ReturnType<typeof vi.fn>).mockResolvedValue(EVAL);
    render(<ToolHubDiscover />);
    fireEvent.change(screen.getByPlaceholderText('capabilities.hero.placeholder'), {
      target: { value: 'owner/repo' },
    });
    fireEvent.click(screen.getByRole('button', { name: /capabilities\.hero\.research/ }));
    await waitFor(() => expect(discovery.evaluateRepo).toHaveBeenCalledWith('owner/repo'));
    expect(await screen.findByTestId('repo-dossier')).toBeInTheDocument();
    expect(screen.getByText('owner/repo')).toBeInTheDocument();
    expect(discovery.searchRepos).not.toHaveBeenCalled();
  });

  it('github URLs also route to evaluate', async () => {
    (discovery.evaluateRepo as ReturnType<typeof vi.fn>).mockResolvedValue(EVAL);
    render(<ToolHubDiscover />);
    fireEvent.change(screen.getByPlaceholderText('capabilities.hero.placeholder'), {
      target: { value: 'https://github.com/owner/repo' },
    });
    fireEvent.click(screen.getByRole('button', { name: /capabilities\.hero\.research/ }));
    await waitFor(() =>
      expect(discovery.evaluateRepo).toHaveBeenCalledWith('https://github.com/owner/repo'));
  });

  it('free-text input searches GitHub and per-row Evaluate opens the dossier', async () => {
    (discovery.searchRepos as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        full_name: 'found/one', html_url: 'https://github.com/found/one', stars: 9, forks: 1,
        license: 'MIT', pushed_days: 1, description: 'hit',
        trust: { tier: 'high', license_note: '' },
      },
    ]);
    (discovery.evaluateRepo as ReturnType<typeof vi.fn>).mockResolvedValue(EVAL);
    render(<ToolHubDiscover />);
    fireEvent.change(screen.getByPlaceholderText('capabilities.hero.placeholder'), {
      target: { value: 'vector database tools' },
    });
    fireEvent.click(screen.getByRole('button', { name: /capabilities\.hero\.research/ }));
    expect(await screen.findByText('found/one')).toBeInTheDocument();
    expect(discovery.evaluateRepo).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /capabilities\.hero\.evaluate/ }));
    await waitFor(() => expect(discovery.evaluateRepo).toHaveBeenCalledWith('found/one'));
    expect(await screen.findByTestId('repo-dossier')).toBeInTheDocument();
  });

  it('shows an honest error when evaluate fails', async () => {
    (discovery.evaluateRepo as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('rate limited'));
    render(<ToolHubDiscover />);
    fireEvent.change(screen.getByPlaceholderText('capabilities.hero.placeholder'), {
      target: { value: 'owner/repo' },
    });
    fireEvent.click(screen.getByRole('button', { name: /capabilities\.hero\.research/ }));
    expect(await screen.findByText(/rate limited/)).toBeInTheDocument();
    expect(screen.queryByTestId('repo-dossier')).toBeNull();
  });
});

describe('RepoDossier', () => {
  it('renders real eval fields: name, stars, description, verdict, type, value line', () => {
    render(<RepoDossier result={EVAL} />);
    expect(screen.getByText('owner/repo')).toBeInTheDocument();
    expect(screen.getByText(/1234/)).toBeInTheDocument(); // real stars, not fabricated
    expect(screen.getByText('A test MCP server for things.')).toBeInTheDocument();
    expect(screen.getByText('capabilities.dossier.license_ok')).toBeInTheDocument();
    expect(screen.getByText('capabilities.dossier.type.mcp')).toBeInTheDocument();
    expect(screen.getByText('Adds a useful capability for Arslan.')).toBeInTheDocument();
    expect(screen.getByText('mcp')).toBeInTheDocument(); // topic chip
  });

  it('permissive license + MCP repo → all contextual actions', () => {
    render(<RepoDossier result={EVAL} />);
    expect(screen.getByRole('button', { name: /actions\.register_skill/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /actions\.add_mcp/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /actions\.distill/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /actions\.save/ })).toBeInTheDocument();
  });

  it('restrictive license → learning-only verdict, no register/MCP actions, distill stays', () => {
    const gpl: EvalResult = {
      ...EVAL,
      repo: { ...EVAL.repo, license: 'GPL-3.0' },
    };
    render(<RepoDossier result={gpl} />);
    expect(screen.getByText('capabilities.dossier.license_learn')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /actions\.register_skill/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /actions\.add_mcp/ })).toBeNull();
    expect(screen.getByRole('button', { name: /actions\.distill/ })).toBeInTheDocument();
  });

  it('Add-as-MCP panel wires the suggested command into addMcpServer', async () => {
    (addMcpServer as ReturnType<typeof vi.fn>).mockResolvedValue({ id: 1 });
    render(<RepoDossier result={EVAL} />);
    fireEvent.click(screen.getByRole('button', { name: /actions\.add_mcp/ }));
    fireEvent.click(screen.getByRole('button', { name: /dossier\.mcp\.add/ }));
    await waitFor(() => expect(addMcpServer).toHaveBeenCalledWith(expect.objectContaining({
      label: 'repo', transport: 'stdio', command: 'npx', args: ['-y', '@owner/repo'],
    })));
    expect(await screen.findByText('capabilities.dossier.mcp.added')).toBeInTheDocument();
  });

  it('Register-as-Skill runs the license-gated scan and imports a SKILL.md', async () => {
    (discovery.scanSkills as ReturnType<typeof vi.fn>).mockResolvedValue({
      repo: { full_name: 'owner/repo', html_url: '', license: 'MIT', stars: 1 },
      license_ok: true,
      license_note: null,
      skills: [{ path: 'skills/x/SKILL.md', name: 'X Skill', description: 'does x', scripts: [], importable: true, reason: null }],
    });
    (discovery.importSkill as ReturnType<typeof vi.fn>).mockResolvedValue({ key: 'x' });
    render(<RepoDossier result={EVAL} />);
    fireEvent.click(screen.getByRole('button', { name: /actions\.register_skill/ }));
    await waitFor(() => expect(discovery.scanSkills).toHaveBeenCalledWith('owner/repo'));
    expect(await screen.findByText('X Skill')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /dossier\.scan\.import/ }));
    await waitFor(() =>
      expect(discovery.importSkill).toHaveBeenCalledWith('owner/repo', 'skills/x/SKILL.md'));
    expect(await screen.findByText(/dossier\.scan\.imported/)).toBeInTheDocument();
  });

  it('Distill uses the LLM skill draft and ingests it into a chosen spawn knowledge base', async () => {
    (discovery.generateSkill as ReturnType<typeof vi.fn>).mockResolvedValue({
      repo: { full_name: 'owner/repo', html_url: '' },
      skill: { name: 'Repo Notes', category: 'reference', description: 'notes', body: '## Trigger\ndistilled body' },
    });
    (api.listSpawns as ReturnType<typeof vi.fn>).mockResolvedValue([{ id: 7, name: 'Mermer' }]);
    (api.ingestKnowledgeText as ReturnType<typeof vi.fn>).mockResolvedValue({ chunks: 1 });
    render(<RepoDossier result={EVAL} />);
    fireEvent.click(screen.getByRole('button', { name: /actions\.distill/ }));
    const body = await screen.findByDisplayValue(/distilled body/);
    expect(body).toBeInTheDocument();
    const picker = await screen.findByLabelText('capabilities.dossier.note.pick_spawn');
    await screen.findByRole('option', { name: 'Mermer' });
    fireEvent.change(picker, { target: { value: '7' } });
    fireEvent.click(screen.getByRole('button', { name: /note\.ingest$/ }));
    await waitFor(() => expect(api.ingestKnowledgeText).toHaveBeenCalledWith(
      7, 'repo:owner/repo', '## Trigger\ndistilled body'));
    expect(await screen.findByText('capabilities.dossier.note.ingest_ok')).toBeInTheDocument();
  });

  it('Distill falls back to a grounded eval-summary note when the LLM distill fails', async () => {
    (discovery.generateSkill as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('no model'));
    render(<RepoDossier result={EVAL} />);
    fireEvent.click(screen.getByRole('button', { name: /actions\.distill/ }));
    expect(await screen.findByText('capabilities.dossier.note.fallback')).toBeInTheDocument();
    // Fallback body is composed from real eval fields only
    const body = await screen.findByDisplayValue(/owner\/repo/);
    expect((body as HTMLTextAreaElement).value).toContain('Stars: 1234');
    expect((body as HTMLTextAreaElement).value).toContain('Adds a useful capability for Arslan.');
    // No LLM body → no register-as-skill button (honest), ingest still offered
    expect(screen.queryByRole('button', { name: /note\.create_skill/ })).toBeNull();
    expect(screen.getByRole('button', { name: /note\.ingest$/ })).toBeInTheDocument();
  });
});

describe('license/type helpers', () => {
  it('permissive allowlist', () => {
    expect(isLicensePermissive('MIT')).toBe(true);
    expect(isLicensePermissive('Apache-2.0')).toBe(true);
    expect(isLicensePermissive('GPL-3.0')).toBe(false);
    expect(isLicensePermissive(null)).toBe(false);
  });

  it('detects repo type from real fields', () => {
    expect(detectRepoKind(EVAL)).toBe('mcp');
    const skillRepo = {
      ...EVAL,
      repo: { ...EVAL.repo, topics: ['skills'], description: 'agent skills pack' },
      suggestion: { ...EVAL.suggestion, is_mcp: false },
    };
    expect(detectRepoKind(skillRepo)).toBe('skill');
    const other = {
      ...EVAL,
      repo: { ...EVAL.repo, full_name: 'a/b', topics: [], description: 'misc' },
      suggestion: { ...EVAL.suggestion, is_mcp: false },
    };
    expect(detectRepoKind(other)).toBe('other');
  });
});
