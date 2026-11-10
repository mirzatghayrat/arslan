/**
 * SUB5d (#819 review): deleting from the window, through the real App, against SUB5a's API on a stubbed fetch.
 *
 * - A sub-session with no sub-sessions of its own: the confirm sheet, then DELETE ?sub_session=true.
 * - A sub-session with its own: the dialog, which names it as a sub-session too (else the server answers 404).
 * - A commander: the dialog, ?sub_sessions=delete.
 * - A commander whose sub-sessions the window doesn't know yet: the server's 422 opens the dialog with its count, and the
 *   row stays.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../i18n';
import App from '../App';
import { initialArslanState, useArslanStore } from '../stores/arslanStore';

class FakeSocket {
  static OPEN = 1;
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) { queueMicrotask(() => this.onopen?.()); }
  send() {}
  close() {}
}
const realSocket = globalThis.WebSocket;

const at = new Date(Date.now() - 60_000).toISOString().replace('Z', '');
const ROWS = [
  { conversation_id: 'cmd', title: 'Commander', message_count: 2, last_at: at, state: 'idle' },
  { conversation_id: 'mid', title: 'Middle', message_count: 2, last_at: at, state: 'done', outcome: 'done', parent_id: 'cmd' },
  { conversation_id: 'leaf', title: 'Leaf', message_count: 2, last_at: at, state: 'done', outcome: 'done', parent_id: 'mid' },
  { conversation_id: 'lone', title: 'Lone', message_count: 2, last_at: at, state: 'idle' },
];
let deletes: string[];

function reply(url: string, init?: RequestInit): { status: number; body: unknown } {
  if ((init?.method ?? 'GET') === 'DELETE') {
    const path = url.replace(/^.*\/api\/v1/, '');
    deletes.push(path);
    if (path === '/conversations/lone') return { status: 422, body: { detail: { code: 'sub_sessions_choice_required', sub_sessions: 3 } } };
    return { status: 200, body: { ok: true, deleted: {} } };
  }
  if (/\/api\/v1\/conversations$/.test(url)) return { status: 200, body: ROWS };
  if (/provider-configs\/\d+\/models/.test(url)) return { status: 200, body: { models: [] } };
  if (/brain\/notes|brain\/proposals|collections|facts|runs|scheduled-tasks|spawns|provider-configs|settings\/(providers|search-providers)/.test(url)) {
    return { status: 200, body: [] };
  }
  return { status: 200, body: /\/settings(\?|$)/.test(url) ? { first_run_seen: true, language: 'en' } : {} };
}

const row = (id: string) => document.getElementById(`active-thread-btn-${id}`)!;
async function deleteFromMenu(id: string) {
  fireEvent.click(row(id).querySelector('[aria-haspopup="menu"]')!);
  fireEvent.click(await screen.findByRole('menuitem', { name: 'Delete' }));
}

beforeEach(async () => {
  deletes = [];
  localStorage.clear();
  sessionStorage.clear();
  useArslanStore.setState(initialArslanState(), true);
  globalThis.WebSocket = FakeSocket as never;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const { status, body } = reply(String(input), init);
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
  });
  render(<App />);
  await waitFor(() => expect(document.getElementById('active-thread-btn-cmd')).not.toBeNull());
  await waitFor(() => expect(screen.getByTestId('sub-toggle-cmd')).toBeInTheDocument());
  fireEvent.click(screen.getByTestId('sub-toggle-cmd'));
  fireEvent.click(screen.getByTestId('sub-toggle-mid'));
  await waitFor(() => expect(document.getElementById('active-thread-btn-leaf')).not.toBeNull());
});
afterEach(() => { cleanup(); globalThis.WebSocket = realSocket; vi.restoreAllMocks(); });

describe('deleting from the window', () => {
  it('deletes a sub-session as one, after the confirm sheet', async () => {
    await deleteFromMenu('leaf');
    await act(async () => { fireEvent.click(await screen.findByTestId('confirm-action')); });
    await waitFor(() => expect(deletes).toEqual(['/conversations/leaf?sub_session=true']));
    await waitFor(() => expect(document.getElementById('active-thread-btn-leaf')).toBeNull());
  });

  it('deletes a sub-session that has its own through the dialog, named as a sub-session', async () => {
    await deleteFromMenu('mid');
    await act(async () => { fireEvent.click(await screen.findByTestId('sub-delete-confirm')); });
    await waitFor(() => expect(deletes).toEqual(['/conversations/mid?sub_sessions=delete&sub_session=true']));
    await waitFor(() => expect(document.getElementById('active-thread-btn-mid')).toBeNull());
    expect(document.getElementById('active-thread-btn-leaf')).toBeNull();
    expect(document.getElementById('active-thread-btn-cmd')).not.toBeNull();
  });

  it('deletes a commander through the dialog, its whole tree', async () => {
    await deleteFromMenu('cmd');
    expect(await screen.findByTestId('sub-delete-dialog')).toHaveTextContent('Also delete its 2 sub-sessions');
    await act(async () => { fireEvent.click(screen.getByTestId('sub-delete-confirm')); });
    await waitFor(() => expect(deletes).toEqual(['/conversations/cmd?sub_sessions=delete']));
  });

  it("opens the dialog with the server's count when the window didn't know its sub-sessions, and keeps the row", async () => {
    await deleteFromMenu('lone');
    await act(async () => { fireEvent.click(await screen.findByTestId('confirm-action')); });
    expect(await screen.findByTestId('sub-delete-dialog')).toHaveTextContent('Also delete its 3 sub-sessions');
    expect(document.getElementById('active-thread-btn-lone')).not.toBeNull();
    await act(async () => { fireEvent.click(screen.getByTestId('sub-delete-confirm')); });
    await waitFor(() => expect(deletes).toEqual(['/conversations/lone', '/conversations/lone?sub_sessions=delete']));
  });
});
