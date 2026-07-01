import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

const addMcpServer = vi.fn(async (..._a: unknown[]) => ({ id: 7 }));
const connectMcpServer = vi.fn(async (..._a: unknown[]) => [] as unknown[]);
const listMcpServers = vi.fn(async (..._a: unknown[]) => [] as unknown[]);
vi.mock('../api/mcp', () => ({
  listMcpServers: (...a: unknown[]) => listMcpServers(...a),
  addMcpServer: (...a: unknown[]) => addMcpServer(...a),
  connectMcpServer: (...a: unknown[]) => connectMcpServer(...a),
}));

import RecommendedMcp from '../components/RecommendedMcp';

function cardFor(label: string) {
  return screen.getByText(label).closest('div.rounded-xl') as HTMLElement;
}

describe('RecommendedMcp', () => {
  beforeEach(() => { addMcpServer.mockClear(); connectMcpServer.mockClear(); listMcpServers.mockClear(); });

  it('one-click card adds then connects (no form)', async () => {
    render(<RecommendedMcp />);
    const memory = cardFor('Memory');
    fireEvent.click(within(memory).getByRole('button', { name: /connect/i }));
    await waitFor(() => expect(addMcpServer).toHaveBeenCalledTimes(1));
    expect(addMcpServer).toHaveBeenCalledWith(expect.objectContaining({
      label: 'Memory', command: 'npx', env: {},
    }));
    // add → connect chained on the returned id
    await waitFor(() => expect(connectMcpServer).toHaveBeenCalledWith(7));
  });

  it('path server refuses to connect until a path is entered', async () => {
    render(<RecommendedMcp />);
    const fs = cardFor('Filesystem');
    fireEvent.click(within(fs).getByRole('button', { name: /connect/i }));
    // no add call — it demands a path first
    expect(addMcpServer).not.toHaveBeenCalled();
    expect(within(fs).getByText(/enter a path/i)).toBeTruthy();
    // with a path, it appends it to the launch args
    fireEvent.change(within(fs).getByPlaceholderText(/path/i), { target: { value: '/tmp/x' } });
    fireEvent.click(within(fs).getByRole('button', { name: /connect/i }));
    await waitFor(() => expect(addMcpServer).toHaveBeenCalledTimes(1));
    const arg = addMcpServer.mock.calls[0][0] as { args: string[] };
    expect(arg.args[arg.args.length - 1]).toBe('/tmp/x');
  });

  it('credentialed card prefills the add form instead of connecting', () => {
    const onPrefillMcp = vi.fn();
    render(<RecommendedMcp onPrefillMcp={onPrefillMcp} />);
    const gh = cardFor('GitHub');
    fireEvent.click(within(gh).getByRole('button', { name: /set up/i }));
    expect(onPrefillMcp).toHaveBeenCalledWith(expect.objectContaining({ label: 'GitHub' }));
    expect(addMcpServer).not.toHaveBeenCalled();
  });
});
