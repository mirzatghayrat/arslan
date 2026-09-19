import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import WorkDock from '../components/WorkDock';
import { browserApi, type ReaderFrame } from '../api/browser';
import { restoreDock, saveDock } from '../lib/workDock';

vi.mock('../components/BrowserPanel', () => ({ default: () => null }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const props = { open: true, onOpen: vi.fn(), onClose: vi.fn(), conversationId: 'private-soon', taskId: null };
const frame: ReaderFrame = { session_id: 'owned-session', conversation_id: props.conversationId, task_id: null,
  revision: 1, title: 'Synthetic', url: 'https://example.com', text: 'Synthetic source', screenshot: 'eA==',
  links: [], can_back: false, can_forward: false, blocked_connections: 0, mode: 'isolated_read_only' };
beforeEach(() => {
  localStorage.clear();
  saveDock([{ id: 'owned-tab', kind: 'browser', conversationId: props.conversationId, taskId: null }], 420, false);
  vi.spyOn(browserApi, 'createReader').mockResolvedValue({ session_id: 'owned-session' });
  vi.spyOn(browserApi, 'readerAction').mockResolvedValue(frame);
  vi.spyOn(browserApi, 'closeReader').mockResolvedValue(undefined);
});
afterEach(() => vi.restoreAllMocks());
function navigate() {
  fireEvent.change(screen.getByLabelText('browser.url'), { target: { value: 'https://example.com' } });
  fireEvent.click(screen.getByLabelText('browser.open'));
}

it('closes the actual reader owner when its conversation becomes temporary', async () => {
  const view = render(<WorkDock {...props} temporary={false} />);
  navigate();
  await screen.findByAltText('browser.screenshot');
  view.rerender(<WorkDock {...props} temporary />);
  await waitFor(() => expect(browserApi.closeReader).toHaveBeenCalledWith('owned-session'));
  expect(screen.queryByAltText('browser.screenshot')).not.toBeInTheDocument();
  expect(restoreDock().tabs).toEqual([]);
  // A new tab created explicitly within the temporary conversation is still
  // usable, but never restored, and is removed when leaving that conversation.
  fireEvent.click(screen.getByLabelText('dock.newBrowser'));
  expect(screen.getByLabelText('browser.url')).toBeInTheDocument();
  expect(restoreDock().tabs).toEqual([]);
  view.rerender(<WorkDock {...props} conversationId="next" temporary={false} />);
  expect(screen.queryByLabelText('browser.url')).not.toBeInTheDocument();
  expect(restoreDock().tabs).toEqual([]);
});

it('closes a late-created session after privacy conversion without navigating it', async () => {
  let resolve!: (value: { session_id: string }) => void;
  vi.mocked(browserApi.createReader).mockReturnValue(new Promise(r => { resolve = r; }));
  const view = render(<WorkDock {...props} temporary={false} />);
  navigate();
  view.rerender(<WorkDock {...props} temporary />);
  await act(async () => { resolve({ session_id: 'late-private-session' }); });
  expect(browserApi.closeReader).toHaveBeenCalledWith('late-private-session');
  expect(browserApi.readerAction).not.toHaveBeenCalled();
  expect(restoreDock().tabs).toEqual([]);
});

it('purges previously saved metadata even when first mounted hidden in temporary mode', () => {
  render(<WorkDock {...props} open={false} temporary />);
  expect(browserApi.createReader).not.toHaveBeenCalled();
  expect(restoreDock().tabs).toEqual([]);
});
