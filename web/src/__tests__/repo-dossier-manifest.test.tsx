/**
 * The manifest card (spec 2026-08-18 Part B, PR-3): an author-shipped
 * arslan.plugin.json replaces the LLM-guessed launch command with declarative
 * truth. Add still goes through the locked addMcpServer path with the
 * manifest's exact config plus whatever the user typed into the secret slots;
 * manifest skills install through the EXISTING verbatim importer. A broken
 * manifest reports one honest line and never hides the guess panel. The
 * author's spawn-expose suggestion renders as ADVICE only — proposing is
 * open, executing is closed.
 */
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
import RepoDossier from '../components/RepoDossier';

const BASE: EvalResult = {
  repo: {
    full_name: 'acme/playwright-pack',
    html_url: 'https://github.com/acme/playwright-pack',
    stars: 10, forks: 1, license: 'MIT', pushed_days: 3,
    description: 'd', topics: [],
  },
  trust: { tier: 'medium', license_note: 'MIT — permissive.' },
  suggestion: { is_mcp: true, transport: 'stdio', command: 'npx',
                args: ['-y', 'guessed'], url: null, reason: 'readme' },
};

const MANIFEST = {
  schema_version: 1 as const, name: 'playwright-pack', version: '0.1.0',
  description: 'Browser automation', min_app_version: null,
  mcp_servers: [{
    label: 'Playwright', transport: 'stdio' as const, command: 'npx',
    args: ['-y', '@playwright/mcp@latest'],
    env: { API_KEY: { secret: true, description: 'key for x' } },
  }],
  skills: ['skills/browsing/SKILL.md'],
  suggest_spawn_expose: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  (api.listSpawns as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  (addMcpServer as ReturnType<typeof vi.fn>).mockResolvedValue({ id: 9 });
  (discovery.importSkill as ReturnType<typeof vi.fn>).mockResolvedValue({ key: 'k', name: 'n' });
});

describe('manifest card', () => {
  it('renders the author-shipped config verbatim', () => {
    render(<RepoDossier result={{ ...BASE, manifest: MANIFEST }} />);
    expect(screen.getByTestId('manifest-card')).toBeTruthy();
    expect(screen.getByText('Playwright')).toBeTruthy();
    expect(screen.getByText(/@playwright\/mcp@latest/)).toBeTruthy();
  });

  it('Add sends the manifest config + typed secrets through the locked path', async () => {
    render(<RepoDossier result={{ ...BASE, manifest: MANIFEST }} />);
    fireEvent.change(screen.getByTestId('manifest-env-API_KEY'), { target: { value: 'sk-1' } });
    fireEvent.click(screen.getByTestId('manifest-add-0'));
    await waitFor(() => expect(addMcpServer).toHaveBeenCalledWith({
      label: 'Playwright', transport: 'stdio', command: 'npx',
      args: ['-y', '@playwright/mcp@latest'], url: null,
      env: { API_KEY: 'sk-1' },
    }));
  });

  it('secret slots render as password inputs', () => {
    render(<RepoDossier result={{ ...BASE, manifest: MANIFEST }} />);
    expect((screen.getByTestId('manifest-env-API_KEY') as HTMLInputElement).type).toBe('password');
  });

  it('manifest skills install through the existing verbatim importer', async () => {
    render(<RepoDossier result={{ ...BASE, manifest: MANIFEST }} />);
    fireEvent.click(screen.getByTestId('manifest-skill-0'));
    await waitFor(() => expect(discovery.importSkill).toHaveBeenCalledWith(
      'acme/playwright-pack', 'skills/browsing/SKILL.md'));
  });

  it('a broken manifest reports one line and keeps the guess panel available', () => {
    render(<RepoDossier
      result={{ ...BASE, manifest_error: 'unsupported schema_version (expected 1)' }} />);
    expect(screen.getByTestId('manifest-error').textContent).toContain('schema_version');
    expect(screen.queryByTestId('manifest-card')).toBeNull();
    expect(screen.getByText('capabilities.dossier.actions.add_mcp')).toBeTruthy();
  });

  it('no manifest → no card, no error line', () => {
    render(<RepoDossier result={BASE} />);
    expect(screen.queryByTestId('manifest-card')).toBeNull();
    expect(screen.queryByTestId('manifest-error')).toBeNull();
  });

  it("the author's spawn-expose suggestion renders as advice, never as an action", () => {
    render(<RepoDossier result={{ ...BASE, manifest: MANIFEST }} />);
    expect(screen.getByText('capabilities.dossier.manifest.expose_hint')).toBeTruthy();
  });
});
