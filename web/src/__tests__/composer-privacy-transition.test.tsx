import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import ConversationControls from '../components/companion/ConversationControls';
import { api } from '../api/client';
import { companionApi, type ConversationContext } from '../api/companion';
import { fileToImagePayload } from '../lib/imagePayload';
import { composerDrafts, discardComposerDraft, getAttachmentDraft } from '../lib/composerDrafts';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('../api/client', async original => ({
  ...await original<typeof import('../api/client')>(),
  api: { extractAttachmentFile: vi.fn(), extractAttachmentUrl: vi.fn() },
}));
vi.mock('../api/companion', () => ({ companionApi: { context: vi.fn(), projects: vi.fn(), saveContext: vi.fn() } }));
vi.mock('../lib/imagePayload', () => ({ fileToImagePayload: vi.fn() }));

const id = 'privacy-transition';
const context: ConversationContext = { conversation_id: id, version: 1, project_id: null,
  no_memory: false, no_learning: false, temporary: false, cloud_memory_allowed: true, allow_sensitive: true };

// Exercise the real settings dialog and composer with App's keyed mount contract.
function Workspace() {
  const [temporary, setTemporary] = useState(false);
  const [visible, setVisible] = useState(true);
  return <>
    <button onClick={() => setVisible(v => !v)}>navigate</button>
    {visible && <>
      <ConversationControls conversationId={id} empty running={false} onChanged={next => setTemporary(next.temporary)} />
      <OrchestratorChat key={`chat:${id}:${temporary}`} conversationId={id}
        activeThread={{ id, title: 'Synthetic', memberSpawnIds: [], temporary }}
        chatHistory={[]} setChatHistory={vi.fn()} spawns={[]} currentStyle="quartz" setCurrentStyle={vi.fn()} />
    </>}
  </>;
}

beforeEach(() => {
  discardComposerDraft(id);
  vi.resetAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  URL.createObjectURL = vi.fn(() => 'blob:private-preview');
  URL.revokeObjectURL = vi.fn();
  vi.mocked(companionApi.context).mockResolvedValue({ ...context });
  vi.mocked(companionApi.projects).mockResolvedValue([]);
  vi.mocked(companionApi.saveContext).mockImplementation(async (_previous, next) => {
    const saved = { ...context, ...next, version: 2 };
    vi.mocked(companionApi.context).mockResolvedValue(saved);
    return saved;
  });
  vi.mocked(fileToImagePayload).mockResolvedValue({ name: 'private.png', mime_type: 'image/png', data: 'QUJD' });
});

async function enableTemporary() {
  const settings = screen.getByRole('button', { name: 'companion.conversationSettings' });
  await waitFor(() => expect(settings).toBeEnabled());
  fireEvent.click(settings);
  fireEvent.click(screen.getByRole('checkbox', { name: 'companion.temporary' }));
  fireEvent.click(screen.getByRole('button', { name: 'companion.save' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
}

describe('composer privacy transition', () => {
  it('keeps the normal draft when the privacy-setting save fails; only confirmation discards it', async () => {
    vi.mocked(companionApi.saveContext).mockRejectedValueOnce(new Error('synthetic save failure'));
    const view = render(<Workspace />);
    fireEvent.change(view.container.querySelector('textarea')!, { target: { value: 'keep until confirmed' } });
    fireEvent.change(view.container.querySelector('input[type="file"]')!, {
      target: { files: [new File(['x'], 'private.png', { type: 'image/png' })] },
    });
    await waitFor(() => expect(getAttachmentDraft(id).items[0]?.image).toBeDefined());
    const settings = screen.getByRole('button', { name: 'companion.conversationSettings' });
    await waitFor(() => expect(settings).toBeEnabled());
    fireEvent.click(settings);
    fireEvent.click(screen.getByRole('checkbox', { name: 'companion.temporary' }));
    expect(composerDrafts.get(id)).toBe('keep until confirmed');
    expect(getAttachmentDraft(id).items).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'companion.save' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(view.container.querySelector('textarea')).toHaveValue('keep until confirmed');
    expect(getAttachmentDraft(id).items).toHaveLength(1);
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'companion.save' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(view.container.querySelector('textarea')).toHaveValue('');
    expect(screen.queryByLabelText('ui.removeAttachment')).not.toBeInTheDocument();
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it('drops regular text/image drafts on confirmed temporary mode and never restores temporary drafts after navigation', async () => {
    const view = render(<Workspace />);
    const input = view.container.querySelector('textarea')!;
    fireEvent.change(input, { target: { value: 'normal draft' } });
    fireEvent.change(view.container.querySelector('input[type="file"]')!, {
      target: { files: [new File(['x'], 'private.png', { type: 'image/png' })] },
    });
    await screen.findByLabelText('ui.removeAttachment');
    await waitFor(() => expect(getAttachmentDraft(id).items[0]?.image).toBeDefined());
    const oldOwner = getAttachmentDraft(id);
    await enableTemporary();
    expect(view.container.querySelector('textarea')).toHaveValue('');
    expect(screen.queryByLabelText('ui.removeAttachment')).not.toBeInTheDocument();
    expect(oldOwner.discarded).toBe(true);
    expect(oldOwner.items).toEqual([]);
    expect(composerDrafts.has(id)).toBe(false);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:private-preview');
    expect(companionApi.saveContext).toHaveBeenCalledWith(context, expect.objectContaining({
      temporary: true, no_memory: true, no_learning: true, cloud_memory_allowed: false, allow_sensitive: false,
    }));

    fireEvent.change(view.container.querySelector('textarea')!, { target: { value: 'temporary draft' } });
    fireEvent.change(view.container.querySelector('input[type="file"]')!, {
      target: { files: [new File(['x'], 'private.png', { type: 'image/png' })] },
    });
    await screen.findByLabelText('ui.removeAttachment');
    await act(async () => { fireEvent.click(screen.getByText('navigate')); });
    await act(async () => { fireEvent.click(screen.getByText('navigate')); });
    expect(view.container.querySelector('textarea')).toHaveValue('');
    expect(screen.queryByLabelText('ui.removeAttachment')).not.toBeInTheDocument();
    expect(composerDrafts.has(id)).toBe(false);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  it('ignores an old pending URL after confirmation and does not extract new temporary URLs', async () => {
    let resolve!: (value: { text: string; chars: number; truncated: boolean }) => void;
    vi.mocked(api.extractAttachmentUrl).mockReturnValue(new Promise(r => { resolve = r; }));
    const view = render(<Workspace />);
    fireEvent.paste(view.container.querySelector('textarea')!, {
      clipboardData: { files: [], getData: () => 'https://example.com/normal' },
    });
    expect(api.extractAttachmentUrl).toHaveBeenCalledTimes(1);
    await enableTemporary();
    await act(async () => { resolve({ text: 'late source', chars: 11, truncated: false }); });
    fireEvent.paste(view.container.querySelector('textarea')!, {
      clipboardData: { files: [], getData: () => 'https://example.com/temporary' },
    });
    expect(api.extractAttachmentUrl).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText('ui.removeAttachment')).not.toBeInTheDocument();
  });
});
