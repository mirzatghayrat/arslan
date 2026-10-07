/** 0.1.55 decision 4, the shell half: the geometry event carries `fullscreen`, and the page follows it. */
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const handlers: Record<string, (e: { payload: unknown }) => void> = {};
vi.mock('@tauri-apps/api/event', () => ({
  listen: async (event: string, cb: (e: { payload: unknown }) => void) => { handlers[event] = cb; return () => {}; },
}));

import IslandApp from '../island/IslandApp';

beforeEach(() => {
  vi.useFakeTimers();
  (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = { invoke: async () => null };
  localStorage.setItem('i18nextLng', 'en');
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.startsWith('/api/v1/island/feed')
    ? { cursor: 1, awaiting: 1, awaiting_conversations: ['c'], active: [], events: [], enabled: true }
    : [{ call_id: 'k', conversation_id: 'c', opened_at: 1, expires_at: 9e9, island_ok: true, frame: { type: 'propose_schedule', name: 'B', when: 'every: 60' } }]),
  { status: 200 })));
});
afterEach(() => {
  cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); localStorage.clear();
  delete (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
});

describe('the shell says a full-screen app is in front', () => {
  it('turns the waiting card into the tab, and back when full screen ends', async () => {
    render(<IslandApp />);
    await act(async () => { await vi.advanceTimersByTimeAsync(20); });
    const island = screen.getByRole('region', { name: 'Arslan Island' });
    expect(island.dataset.mode).toBe('expanded');
    await act(async () => { handlers['island-geometry']({ payload: { notch: true, notchWidth: 188, barHeight: 32, fullscreen: true } }); });
    expect(island.dataset.mode).toBe('tab');
    await act(async () => { handlers['island-geometry']({ payload: { notch: true, notchWidth: 188, barHeight: 32, fullscreen: false } }); });
    expect(island.dataset.mode).toBe('expanded');
  });
});
