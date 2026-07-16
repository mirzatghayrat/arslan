import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { McpConnector } from '../api/client.types';

// Guard (also enforced by a repo-wide grep for the old preset module's name in web/src,
// run as part of the Task 4 gate — must be empty): RecommendedMcp must read GET /mcp/catalog
// via ../api/catalog, never the deleted static data/ module. Mocking ../api/catalog below and
// asserting the component renders exclusively from that mock's data is the runtime half of
// that guard.

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

const getMcpCatalog = vi.fn(async () => [] as McpConnector[]);
vi.mock('../api/catalog', () => ({
  getMcpCatalog: () => getMcpCatalog(),
}));

const addMcpServer = vi.fn(async (..._a: unknown[]) => ({ id: 7 }));
const connectMcpServer = vi.fn(async (..._a: unknown[]) => [] as unknown[]);
const listMcpServers = vi.fn(async (..._a: unknown[]) => [] as unknown[]);
vi.mock('../api/mcp', () => ({
  listMcpServers: (...a: unknown[]) => listMcpServers(...a),
  addMcpServer: (...a: unknown[]) => addMcpServer(...a),
  connectMcpServer: (...a: unknown[]) => connectMcpServer(...a),
}));

import RecommendedMcp from '../components/RecommendedMcp';

// Three fixture connectors shaped exactly like GET /mcp/catalog (server/mcp/catalog.py) —
// one credential-free (one_click), one credentialed (env non-empty), one credential-free
// but path-gated (requires_path — the Filesystem/Git shape this regression test guards).
const MEMORY: McpConnector = {
  key: 'memory', label: 'Memory', transport: 'stdio', command: 'npx',
  args: ['-y', '@modelcontextprotocol/server-memory'], url: null, runtime: 'node',
  description: 'Persistent knowledge-graph memory (stored locally).', one_click: true, env: [],
  requires_path: false, path_placeholder: null,
};
const GITHUB: McpConnector = {
  key: 'github', label: 'GitHub', transport: 'stdio', command: 'npx',
  args: ['-y', '@modelcontextprotocol/server-github'], url: null, runtime: 'node',
  description: 'GitHub repo / issue / PR access.', one_click: false,
  env: [{
    name: 'GITHUB_PERSONAL_ACCESS_TOKEN',
    description: 'A GitHub personal access token (classic or fine-grained).',
    get_it_url: 'https://github.com/settings/tokens',
    paid: false,
  }],
  requires_path: false, path_placeholder: null,
};
const FILESYSTEM: McpConnector = {
  key: 'filesystem', label: 'Filesystem', transport: 'stdio', command: 'npx',
  args: ['-y', '@modelcontextprotocol/server-filesystem'], url: null, runtime: 'node',
  description: 'Read and write files under a directory you choose. Takes a local path.',
  one_click: true, env: [],
  requires_path: true, path_placeholder: '/absolute/path/to/expose',
};

describe('RecommendedMcp (reads GET /mcp/catalog via getMcpCatalog)', () => {
  beforeEach(() => {
    addMcpServer.mockClear();
    connectMcpServer.mockClear();
    listMcpServers.mockClear();
    getMcpCatalog.mockReset();
    getMcpCatalog.mockResolvedValue([MEMORY, GITHUB]);
  });

  it('fetches the catalog on mount and renders a card per connector', async () => {
    render(<RecommendedMcp />);
    await waitFor(() => expect(getMcpCatalog).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('Memory')).toBeInTheDocument();
    expect(await screen.findByText('GitHub')).toBeInTheDocument();
  });

  it('one-click connector (env: []) adds then connects (no form)', async () => {
    render(<RecommendedMcp />);
    const memory = await screen.findByText('Memory');
    const card = memory.closest('div.rounded-xl') as HTMLElement;
    fireEvent.click(within(card).getByRole('button', { name: /connect/i }));
    await waitFor(() => expect(addMcpServer).toHaveBeenCalledTimes(1));
    expect(addMcpServer).toHaveBeenCalledWith(expect.objectContaining({
      label: 'Memory', command: 'npx', env: {},
    }));
    // add → connect chained on the returned id
    await waitFor(() => expect(connectMcpServer).toHaveBeenCalledWith(7));
  });

  it('requires_path connector renders a path input and does NOT connect until a path is entered', async () => {
    getMcpCatalog.mockResolvedValue([FILESYSTEM]);
    render(<RecommendedMcp />);
    const fs = await screen.findByText('Filesystem');
    const card = fs.closest('div.rounded-xl') as HTMLElement;
    const connectBtn = within(card).getByRole('button', { name: /connect/i });

    // Clicking Connect with no path typed must not add/connect — it's a deterministic
    // client-side gate (the old RecommendedMcp.tsx behavior ported from mcpPresets.ts),
    // and it must show an actionable error rather than silently doing nothing.
    fireEvent.click(connectBtn);
    expect(addMcpServer).not.toHaveBeenCalled();
    expect(connectMcpServer).not.toHaveBeenCalled();
    expect(await within(card).findByText(/enter a path/i)).toBeInTheDocument();

    // Placeholder disclosed to the user before they type.
    const input = within(card).getByPlaceholderText('/absolute/path/to/expose');
    expect(input).toBeInTheDocument();
    fireEvent.change(input, { target: { value: '/Users/me/projects/demo' } });
    fireEvent.click(connectBtn);

    await waitFor(() => expect(addMcpServer).toHaveBeenCalledTimes(1));
    // The typed path is appended to args, matching the old mcpPresets.ts contract:
    // filesystem → [...args, "<path>"].
    expect(addMcpServer).toHaveBeenCalledWith(expect.objectContaining({
      label: 'Filesystem', command: 'npx', env: {},
      args: ['-y', '@modelcontextprotocol/server-filesystem', '/Users/me/projects/demo'],
    }));
    await waitFor(() => expect(connectMcpServer).toHaveBeenCalledWith(7));
  });

  it('credentialed connector (env non-empty) prefills the add form instead of connecting', async () => {
    const onPrefillMcp = vi.fn();
    render(<RecommendedMcp onPrefillMcp={onPrefillMcp} />);
    const gh = await screen.findByText('GitHub');
    const card = gh.closest('div.rounded-xl') as HTMLElement;
    fireEvent.click(within(card).getByRole('button', { name: /set up/i }));
    expect(onPrefillMcp).toHaveBeenCalledWith(expect.objectContaining({
      label: 'GitHub', command: 'npx', transport: 'stdio',
      envKeys: ['GITHUB_PERSONAL_ACCESS_TOKEN'],
    }));
    expect(addMcpServer).not.toHaveBeenCalled();
  });

  it('renders nothing extra when the catalog is empty (no static fallback data)', async () => {
    getMcpCatalog.mockResolvedValue([]);
    render(<RecommendedMcp />);
    await waitFor(() => expect(getMcpCatalog).toHaveBeenCalledTimes(1));
    expect(screen.queryByText('Memory')).not.toBeInTheDocument();
    expect(screen.queryByText('GitHub')).not.toBeInTheDocument();
  });
});
