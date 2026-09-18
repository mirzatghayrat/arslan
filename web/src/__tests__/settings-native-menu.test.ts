import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';

const { refresh } = vi.hoisted(() => ({ refresh: vi.fn().mockResolvedValue(null) }));
vi.mock('../lib/updater', () => ({ fetchUpdateStatus: refresh }));

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe('native menu language refresh', () => {
  it('refreshes only after the language write completes', async () => {
    let finish!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; })));
    const pending = api.updateSettings({ language: 'ja' });
    expect(refresh).not.toHaveBeenCalled();
    finish(new Response(JSON.stringify({ language: 'ja' }), { status: 200 }));
    expect(await pending).toEqual({ language: 'ja' });
    expect(refresh).toHaveBeenCalledOnce();
    expect(refresh).toHaveBeenCalledWith();
  });

  it('does not refresh when persistence fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 500 })));
    await expect(api.updateSettings({ language: 'fr' })).rejects.toThrow();
    expect(refresh).not.toHaveBeenCalled();
  });

  it('does not refresh for unrelated settings', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })));
    await api.updateSettings({ first_run_seen: true });
    expect(refresh).not.toHaveBeenCalled();
  });
});
