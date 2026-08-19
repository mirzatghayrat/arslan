/**
 * Discover UX round (user asks 2026-08-20):
 * ① RESEARCH busy state stays a solid, labelled button (not a half-dead fade);
 *    results fade in instead of popping.
 * ② the dossier shows a plain-language overview (what + use cases) for
 *    non-programmers, replacing the "无法确定 + copyleft warning" value line.
 * ③ search rows carry a type badge (MCP/Skill/Agent/Other) and topic tags,
 *    and a filter chip row narrows results by kind — no LLM call needed, the
 *    kind is derived from name/description/topics.
 */
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
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
vi.mock('../api/mcp', () => ({ addMcpServer: vi.fn() }));
vi.mock('../api/client', () => ({
  api: { listSpawns: vi.fn(async () => []), ingestKnowledgeText: vi.fn() },
}));

import * as discovery from '../api/discovery';
import type { EvalResult } from '../api/discovery';
import ToolHubDiscover from '../components/ToolHubDiscover';
import RepoDossier, { detectKindFromFields } from '../components/RepoDossier';

const OVERVIEW = { what: 'A screenshot tool for your desktop.',
                   use_cases: ['Grab a region', 'Annotate a bug', 'Share a snip'] };

const EVAL: EvalResult = {
  repo: { full_name: 'flameshot-org/flameshot', html_url: 'u', stars: 30641, forks: 1994,
          license: 'GPL-3.0', pushed_days: 0, description: 'Powerful screenshot software',
          topics: ['capture', 'screenshot'] },
  trust: { tier: 'high', license_note: 'GPL-3.0: copyleft — 传染性警告' },
  suggestion: { is_mcp: false, transport: null, command: null, args: [], url: null, reason: '无法确定' },
  overview: OVERVIEW,
};

beforeEach(() => {
  vi.clearAllMocks();
});

// ── ③ detectKindFromFields: works on search-row fields (no LLM verdict) ──────
describe('detectKindFromFields', () => {
  it('flags MCP from topics/name even without the LLM is_mcp verdict', () => {
    expect(detectKindFromFields({ full_name: 'acme/mcp-thing', description: '', topics: ['mcp'] })).toBe('mcp');
    expect(detectKindFromFields({ full_name: 'a/b', description: 'a model context protocol server', topics: [] })).toBe('mcp');
  });
  it('honors an explicit is_mcp verdict first', () => {
    expect(detectKindFromFields({ full_name: 'a/b', description: 'x', topics: [], is_mcp: true })).toBe('mcp');
  });
  it('detects skill and agent, else other', () => {
    expect(detectKindFromFields({ full_name: 'a/cool-skill', description: '', topics: [] })).toBe('skill');
    expect(detectKindFromFields({ full_name: 'a/b', description: 'an autonomous agent', topics: [] })).toBe('agent');
    expect(detectKindFromFields({ full_name: 'a/flameshot', description: 'screenshots', topics: ['gui'] })).toBe('other');
  });
});

// ── ② dossier overview ──────────────────────────────────────────────────────
describe('dossier overview', () => {
  it('renders the plain-language what + use cases', () => {
    render(<RepoDossier result={EVAL} />);
    const card = screen.getByTestId('overview-card');
    expect(within(card).getByText('A screenshot tool for your desktop.')).toBeTruthy();
    expect(within(card).getByText('Grab a region')).toBeTruthy();
    expect(within(card).getByText('Share a snip')).toBeTruthy();
  });
  it('hides the overview card when the backend returned an empty overview', () => {
    render(<RepoDossier result={{ ...EVAL, overview: { what: '', use_cases: [] } }} />);
    expect(screen.queryByTestId('overview-card')).toBeNull();
  });
});

// ── ③ search rows: type badge + topics + filter chips ───────────────────────
describe('search type badges and filter', () => {
  const items = [
    { full_name: 'acme/mcp-thing', html_url: 'u', stars: 500, forks: 3, license: 'MIT',
      pushed_days: 2, description: 'an mcp server', topics: ['mcp'], trust: { tier: 'high', license_note: '' } },
    { full_name: 'acme/flameshot', html_url: 'u', stars: 30000, forks: 1000, license: 'GPL-3.0',
      pushed_days: 0, description: 'screenshots', topics: ['gui'], trust: { tier: 'high', license_note: '' } },
  ];

  it('shows a kind badge and topic tags on each row', async () => {
    (discovery.searchRepos as ReturnType<typeof vi.fn>).mockResolvedValue(items);
    render(<ToolHubDiscover />);
    fireEvent.change(screen.getByPlaceholderText('capabilities.hero.placeholder'), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('capabilities.hero.research'));
    await waitFor(() => expect(screen.getByTestId('kind-badge-acme/mcp-thing')).toBeTruthy());
    expect(screen.getByTestId('kind-badge-acme/mcp-thing').textContent).toContain('mcp');
    expect(screen.getByTestId('kind-badge-acme/flameshot').textContent).toContain('other');
    expect(screen.getByText('#mcp')).toBeTruthy();
  });

  it('filter chips narrow the visible rows by kind', async () => {
    (discovery.searchRepos as ReturnType<typeof vi.fn>).mockResolvedValue(items);
    render(<ToolHubDiscover />);
    fireEvent.change(screen.getByPlaceholderText('capabilities.hero.placeholder'), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('capabilities.hero.research'));
    await waitFor(() => expect(screen.getByText('acme/mcp-thing')).toBeTruthy());
    fireEvent.click(screen.getByTestId('filter-chip-mcp'));
    expect(screen.getByText('acme/mcp-thing')).toBeTruthy();
    expect(screen.queryByText('acme/flameshot')).toBeNull();
  });
});
