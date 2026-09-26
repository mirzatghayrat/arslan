import { StrictMode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useComposerAttach } from '../components/ComposerAttach';
import { discardComposerDraft, getAttachmentDraft } from '../lib/composerDrafts';
import { fileToImagePayload } from '../lib/imagePayload';
import { api } from '../api/client';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('../lib/imagePayload', () => ({ fileToImagePayload: vi.fn() }));
vi.mock('../api/client', () => ({ api: { extractAttachmentFile: vi.fn(), extractAttachmentUrl: vi.fn() } }));

function Harness({ id, temporary = false }: { id: string; temporary?: boolean }) {
  const attach = useComposerAttach(() => {}, false, { draft: temporary ? undefined : getAttachmentDraft(id) });
  return <>
    <output>{attach.attachments.map(a => a.name).join(',')}</output>
    <button onClick={() => attach.addFiles([new File(['x'], 'photo.png', { type: 'image/png' })])}>add</button>
    <button onClick={() => attach.removeAt(0)}>remove</button>
    <button onClick={() => attach.clear({ revokeUrls: false })}>send</button>
    <button onClick={() => attach.clear()}>clear</button>
    <button onClick={() => attach.addFiles([new File(['text'], 'draft.txt', { type: 'text/plain' })])}>document</button>
  </>;
}

beforeEach(() => {
  for (const id of ['a', 'b']) discardComposerDraft(id);
  vi.clearAllMocks();
  URL.createObjectURL = vi.fn(() => 'blob:draft');
  URL.revokeObjectURL = vi.fn();
  vi.mocked(fileToImagePayload).mockResolvedValue({ name: 'photo.png', mime_type: 'image/png', data: 'QUJD' });
});
async function add() { await act(async () => { fireEvent.click(screen.getByText('add')); }); }

describe('session attachment drafts', () => {
  it('restores prepared images across unmount and StrictMode, isolated by conversation', async () => {
    const first = render(<Harness id="a" />);
    await add();
    first.unmount();
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    const other = render(<Harness id="b" />);
    expect(screen.getByRole('status')).toHaveTextContent('');
    other.unmount();
    render(<StrictMode><Harness id="a" /></StrictMode>);
    expect(screen.getByRole('status')).toHaveTextContent('photo.png');
    expect(fileToImagePayload).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  });

  it.each(['remove', 'clear', 'send'])('%s clears the retained draft with correct preview ownership', async action => {
    const view = render(<Harness id="a" />);
    await add();
    fireEvent.click(screen.getByText(action));
    view.unmount();
    render(<Harness id="a" />);
    expect(screen.getByRole('status')).toHaveTextContent('');
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(action === 'send' ? 0 : 1);
  });

  it('drops pending preparation and ignores late results', async () => {
    let resolve!: (value: Awaited<ReturnType<typeof fileToImagePayload>>) => void;
    vi.mocked(fileToImagePayload).mockReturnValue(new Promise(r => { resolve = r; }));
    const view = render(<Harness id="a" />);
    fireEvent.click(screen.getByText('add'));
    view.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:draft');
    await act(async () => { resolve({ name: 'photo.png', mime_type: 'image/png', data: 'QUJD' }); });
    render(<Harness id="a" />);
    expect(screen.getByRole('status')).toHaveTextContent('');
  });

  it('discard cannot be undone by the old mounted owner cleanup', async () => {
    const view = render(<Harness id="a" />);
    await add();
    discardComposerDraft('a');
    view.unmount();
    render(<Harness id="a" />);
    expect(screen.getByRole('status')).toHaveTextContent('');
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it('does not resurrect a document extraction completed after navigation', async () => {
    let resolve!: (value: { text: string; chars: number; truncated: boolean }) => void;
    vi.mocked(api.extractAttachmentFile).mockReturnValue(new Promise(r => { resolve = r; }));
    const view = render(<Harness id="a" />);
    fireEvent.click(screen.getByText('document'));
    view.unmount();
    await act(async () => { resolve({ text: 'late', chars: 4, truncated: false }); });
    render(<Harness id="a" />);
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  it('temporary attachments are released on unmount, not retained', async () => {
    const view = render(<Harness id="a" temporary />);
    await add();
    view.unmount();
    render(<Harness id="a" temporary />);
    expect(screen.getByRole('status')).toHaveTextContent('');
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });
});
