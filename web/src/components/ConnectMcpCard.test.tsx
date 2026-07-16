import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, test, expect, vi, afterEach } from 'vitest';
import { applyConnectMcp } from './ConnectMcpCard';
import * as mcpApi from '../api/mcp';

afterEach(() => vi.restoreAllMocks());

// ── applyConnectMcp: the load-bearing per-tier apply chain ─────────────────────

describe('applyConnectMcp', () => {
  test('wires each discovered tool at its suggested_tier, never blanket safe', async () => {
    vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 7 } as any);
    vi.spyOn(mcpApi, 'connectMcpServer').mockResolvedValue([
      { key: 'mcp_7__list_repos', name: 'list_repos', suggested_tier: 'safe' },
      { key: 'mcp_7__delete_repo', name: 'delete_repo', suggested_tier: 'orchestrator' },
    ] as any);
    vi.spyOn(mcpApi, 'exposeMcpServer').mockResolvedValue({ ok: true });
    const wire = vi.spyOn(mcpApi, 'wireMcpTool').mockResolvedValue({ ok: true });

    const res = await applyConnectMcp({
      label: 'GitHub', transport: 'stdio', command: 'npx', args: ['-y', 'x'], url: null,
      env: { GITHUB_PERSONAL_ACCESS_TOKEN: 'ghp_xxx' },
    });

    // delete_repo must NOT be wired safe — chat must not widen the grant vs Settings.
    expect(wire).toHaveBeenCalledWith('mcp_7__list_repos', 'safe', true);
    expect(wire).toHaveBeenCalledWith('mcp_7__delete_repo', 'orchestrator', true);
    expect(res).toEqual({ ok: true, serverId: 7, toolCount: 2, safeCount: 1, restrictedCount: 1, assignable: true });
  });

  test('all-restricted connector reports not-assignable', async () => {
    vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 8 } as any);
    vi.spyOn(mcpApi, 'connectMcpServer').mockResolvedValue([
      { key: 'mcp_8__delete', name: 'delete', suggested_tier: 'orchestrator' },
    ] as any);
    vi.spyOn(mcpApi, 'exposeMcpServer').mockResolvedValue({ ok: true });
    vi.spyOn(mcpApi, 'wireMcpTool').mockResolvedValue({ ok: true });
    const res = await applyConnectMcp({ label: 'X', transport: 'stdio', command: 'c', args: [], url: null, env: {} });
    expect(res.assignable).toBe(false);
  });

  test('connect failure reports the stopped state, not a bare fail', async () => {
    vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 9 } as any);
    vi.spyOn(mcpApi, 'connectMcpServer').mockRejectedValue(new Error('bad token'));
    const res = await applyConnectMcp({ label: 'X', transport: 'stdio', command: 'c', args: [], url: null, env: {} });
    expect(res.ok).toBe(false);
    expect(res.stage).toBe('connect');              // where it stopped
    expect(res.message).toMatch(/Settings/);         // where to fix
  });

  test('add failure reports stage "add" with an actionable message', async () => {
    vi.spyOn(mcpApi, 'addMcpServer').mockRejectedValue(new Error('boom'));
    const res = await applyConnectMcp({ label: 'X', transport: 'stdio', command: 'c', args: [], url: null, env: {} });
    expect(res.ok).toBe(false);
    expect(res.stage).toBe('add');
    expect(res.message).toMatch(/Settings/);
  });

  test('expose failure reports stage "expose" and still carries the serverId', async () => {
    vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 11 } as any);
    vi.spyOn(mcpApi, 'connectMcpServer').mockResolvedValue([] as any);
    vi.spyOn(mcpApi, 'exposeMcpServer').mockRejectedValue(new Error('nope'));
    const res = await applyConnectMcp({ label: 'X', transport: 'stdio', command: 'c', args: [], url: null, env: {} });
    expect(res.ok).toBe(false);
    expect(res.stage).toBe('expose');
    expect(res.serverId).toBe(11);
    expect(res.message).toMatch(/Settings/);
  });

  test('a wire failure mid-loop returns a stage "wire" failure, not a throw', async () => {
    vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 13 } as any);
    vi.spyOn(mcpApi, 'connectMcpServer').mockResolvedValue([
      { key: 'mcp_13__list_repos', name: 'list_repos', suggested_tier: 'safe' },
      { key: 'mcp_13__delete_repo', name: 'delete_repo', suggested_tier: 'orchestrator' },
    ] as any);
    vi.spyOn(mcpApi, 'exposeMcpServer').mockResolvedValue({ ok: true });
    vi.spyOn(mcpApi, 'wireMcpTool').mockRejectedValue(new Error('wire boom'));

    const res = await applyConnectMcp({
      label: 'GitHub', transport: 'stdio', command: 'npx', args: ['-y', 'x'], url: null, env: {},
    });

    expect(res.ok).toBe(false);
    expect(res.stage).toBe('wire');
    expect(res.serverId).toBe(13);
    expect(res.message).toMatch(/Settings/);
  });

  test('secret values reach addMcpServer only — never appear on wireMcpTool/connectMcpServer calls', async () => {
    const add = vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 12 } as any);
    const connect = vi.spyOn(mcpApi, 'connectMcpServer').mockResolvedValue([
      { key: 'mcp_12__list_repos', name: 'list_repos', suggested_tier: 'safe' },
    ] as any);
    vi.spyOn(mcpApi, 'exposeMcpServer').mockResolvedValue({ ok: true });
    const wire = vi.spyOn(mcpApi, 'wireMcpTool').mockResolvedValue({ ok: true });

    await applyConnectMcp({
      label: 'GitHub', transport: 'stdio', command: 'npx', args: ['-y', 'x'], url: null,
      env: { GITHUB_PERSONAL_ACCESS_TOKEN: 'ghp_super_secret' },
    });

    expect(add).toHaveBeenCalledWith(expect.objectContaining({
      env: { GITHUB_PERSONAL_ACCESS_TOKEN: 'ghp_super_secret' },
    }));
    // connect/wire take only ids/keys/tiers — assert the secret string never appears.
    expect(connect.mock.calls.flat()).not.toContain('ghp_super_secret');
    expect(wire.mock.calls.flat().join(' ')).not.toContain('ghp_super_secret');
  });
});

// ── ConnectMcpCard: rendering, prerequisite disclosure, requires_path gate ─────

import ConnectMcpCard from './ConnectMcpCard';

describe('ConnectMcpCard', () => {
  test('discloses prerequisites and collects each env value in a password field', async () => {
    vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 20 } as any);
    vi.spyOn(mcpApi, 'connectMcpServer').mockResolvedValue([
      { key: 'mcp_20__list_repos', name: 'list_repos', suggested_tier: 'safe' },
    ] as any);
    vi.spyOn(mcpApi, 'exposeMcpServer').mockResolvedValue({ ok: true });
    vi.spyOn(mcpApi, 'wireMcpTool').mockResolvedValue({ ok: true });

    const onApplied = vi.fn();
    render(
      <ConnectMcpCard
        callId="c1"
        label="GitHub"
        transport="stdio"
        command="npx"
        args={['-y', '@modelcontextprotocol/server-github']}
        url={null}
        envKeys={[{
          name: 'GITHUB_PERSONAL_ACCESS_TOKEN',
          description: 'A GitHub personal access token.',
          get_it_url: 'https://github.com/settings/tokens',
          paid: false,
        }]}
        prerequisites="Needs a GitHub personal access token."
        onApplied={onApplied}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText(/Needs a GitHub personal access token/)).toBeInTheDocument();
    const tokenInput = screen.getByLabelText('GITHUB_PERSONAL_ACCESS_TOKEN');
    expect(tokenInput).toHaveAttribute('type', 'password');
    expect(tokenInput).toHaveAttribute('autoComplete', 'off');
    fireEvent.change(tokenInput, { target: { value: 'ghp_xxx' } });

    fireEvent.click(screen.getByTestId('connect-mcp-connect'));

    await waitFor(() => expect(mcpApi.addMcpServer).toHaveBeenCalledWith(expect.objectContaining({
      env: { GITHUB_PERSONAL_ACCESS_TOKEN: 'ghp_xxx' },
    })));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(expect.objectContaining({ ok: true })));
  });

  test('on success shows the honest local ready/restricted copy', async () => {
    vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 21 } as any);
    vi.spyOn(mcpApi, 'connectMcpServer').mockResolvedValue([
      { key: 'a', name: 'a', suggested_tier: 'safe' },
      { key: 'b', name: 'b', suggested_tier: 'orchestrator' },
    ] as any);
    vi.spyOn(mcpApi, 'exposeMcpServer').mockResolvedValue({ ok: true });
    vi.spyOn(mcpApi, 'wireMcpTool').mockResolvedValue({ ok: true });

    render(
      <ConnectMcpCard
        callId="c1" label="X" transport="stdio" command="c" args={[]} url={null}
        envKeys={[]} onApplied={vi.fn()} onCancel={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId('connect-mcp-connect'));
    expect(await screen.findByText(/Connected — 1 ready, 1 restricted/)).toBeInTheDocument();
  });

  test('all-restricted success shows a needs-review copy, not "ready"', async () => {
    vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 22 } as any);
    vi.spyOn(mcpApi, 'connectMcpServer').mockResolvedValue([
      { key: 'a', name: 'a', suggested_tier: 'orchestrator' },
    ] as any);
    vi.spyOn(mcpApi, 'exposeMcpServer').mockResolvedValue({ ok: true });
    vi.spyOn(mcpApi, 'wireMcpTool').mockResolvedValue({ ok: true });

    render(
      <ConnectMcpCard
        callId="c1" label="X" transport="stdio" command="c" args={[]} url={null}
        envKeys={[]} onApplied={vi.fn()} onCancel={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId('connect-mcp-connect'));
    expect(await screen.findByText(/needs review in Settings/)).toBeInTheDocument();
    expect(screen.queryByText(/ready/)).not.toBeInTheDocument();
  });

  test('failure shows the state-aware message, not a bare fail', async () => {
    vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 23 } as any);
    vi.spyOn(mcpApi, 'connectMcpServer').mockRejectedValue(new Error('bad token'));

    render(
      <ConnectMcpCard
        callId="c1" label="X" transport="stdio" command="c" args={[]} url={null}
        envKeys={[]} onApplied={vi.fn()} onCancel={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId('connect-mcp-connect'));
    expect(await screen.findByText(/retry in Settings/)).toBeInTheDocument();
  });

  test('wire failure unsticks the card from "Connecting…" and shows the wire message', async () => {
    vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 24 } as any);
    vi.spyOn(mcpApi, 'connectMcpServer').mockResolvedValue([
      { key: 'a', name: 'a', suggested_tier: 'safe' },
    ] as any);
    vi.spyOn(mcpApi, 'exposeMcpServer').mockResolvedValue({ ok: true });
    vi.spyOn(mcpApi, 'wireMcpTool').mockRejectedValue(new Error('wire boom'));

    const onApplied = vi.fn();
    render(
      <ConnectMcpCard
        callId="c1" label="X" transport="stdio" command="c" args={[]} url={null}
        envKeys={[]} onApplied={onApplied} onCancel={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId('connect-mcp-connect'));
    expect(await screen.findByText(/couldn't finish wiring/i)).toBeInTheDocument();
    // Not stuck: the button no longer reads "Connecting…" and onApplied fired.
    expect(screen.queryByText(/Connecting…/)).not.toBeInTheDocument();
    expect(onApplied).toHaveBeenCalledWith(expect.objectContaining({ ok: false, stage: 'wire' }));
  });

  test('cancel fires onCancel with the call id and makes no API calls', () => {
    const addSpy = vi.spyOn(mcpApi, 'addMcpServer');
    const onCancel = vi.fn();
    render(
      <ConnectMcpCard
        callId="cX" label="X" transport="stdio" command="c" args={[]} url={null}
        envKeys={[]} onApplied={vi.fn()} onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByTestId('connect-mcp-cancel'));
    expect(onCancel).toHaveBeenCalledWith('cX');
    expect(addSpy).not.toHaveBeenCalled();
  });

  // ── requires_path (Filesystem/Git): plain text field, gated Connect, args append ──

  test('requires_path connector does not connect until a path is entered', async () => {
    const addSpy = vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 30 } as any);
    vi.spyOn(mcpApi, 'connectMcpServer').mockResolvedValue([] as any);
    vi.spyOn(mcpApi, 'exposeMcpServer').mockResolvedValue({ ok: true });
    vi.spyOn(mcpApi, 'wireMcpTool').mockResolvedValue({ ok: true });

    render(
      <ConnectMcpCard
        callId="c1" label="Filesystem" transport="stdio" command="npx"
        args={['-y', '@modelcontextprotocol/server-filesystem']} url={null}
        envKeys={[]} requiresPath pathPlaceholder="/absolute/path/to/expose"
        onApplied={vi.fn()} onCancel={vi.fn()}
      />,
    );

    // The path field is plain text, never password — it is not a secret.
    const pathInput = screen.getByLabelText('local path');
    expect(pathInput).toHaveAttribute('type', 'text');
    expect(pathInput).toHaveAttribute('placeholder', '/absolute/path/to/expose');

    fireEvent.click(screen.getByTestId('connect-mcp-connect'));
    expect(addSpy).not.toHaveBeenCalled();
    expect(await screen.findByText(/enter a path/i)).toBeInTheDocument();

    fireEvent.change(pathInput, { target: { value: '/Users/me/projects/demo' } });
    fireEvent.click(screen.getByTestId('connect-mcp-connect'));

    await waitFor(() => expect(addSpy).toHaveBeenCalledWith(expect.objectContaining({
      args: ['-y', '@modelcontextprotocol/server-filesystem', '/Users/me/projects/demo'],
    })));
  });

  test('requires_path appends the path to a NEW args array without mutating the original', async () => {
    vi.spyOn(mcpApi, 'addMcpServer').mockResolvedValue({ id: 31 } as any);
    vi.spyOn(mcpApi, 'connectMcpServer').mockResolvedValue([] as any);
    vi.spyOn(mcpApi, 'exposeMcpServer').mockResolvedValue({ ok: true });
    vi.spyOn(mcpApi, 'wireMcpTool').mockResolvedValue({ ok: true });

    const frameArgs = ['mcp-server-git', '--repository'];
    render(
      <ConnectMcpCard
        callId="c1" label="Git" transport="stdio" command="uvx"
        args={frameArgs} url={null}
        envKeys={[]} requiresPath pathPlaceholder="/absolute/path/to/git/repo"
        onApplied={vi.fn()} onCancel={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText('local path'), { target: { value: '/repo' } });
    fireEvent.click(screen.getByTestId('connect-mcp-connect'));

    await waitFor(() => expect(mcpApi.addMcpServer).toHaveBeenCalledWith(expect.objectContaining({
      args: ['mcp-server-git', '--repository', '/repo'],
    })));
    // The frame's own args array is untouched (no in-place mutation).
    expect(frameArgs).toEqual(['mcp-server-git', '--repository']);
  });
});
