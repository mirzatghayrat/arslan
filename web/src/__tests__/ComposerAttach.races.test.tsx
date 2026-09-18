import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useComposerAttach } from '../components/ComposerAttach';
import { api } from '../api/client';
import { fileToImagePayload } from '../lib/imagePayload';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('../api/client', () => ({ api: { extractAttachmentFile: vi.fn(), extractAttachmentUrl: vi.fn() } }));
vi.mock('../lib/imagePayload', () => ({ fileToImagePayload: vi.fn() }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const extracted = { text: 'source', chars: 6, truncated: false };
const doc = (name: string) => new File(['source'], name);

beforeEach(() => {
  vi.resetAllMocks();
  URL.createObjectURL = vi.fn(() => 'blob:synthetic');
  URL.revokeObjectURL = vi.fn();
});

describe('attachment async ownership', () => {
  it('does not extract pasted URLs when the temporary-conversation policy disables it', () => {
    const { result } = renderHook(() => useComposerAttach(vi.fn(), false, { allowUrlExtraction: false }));
    act(() => result.current.onPaste({ clipboardData: { files: [], getData: () => 'https://example.com/private' } } as never));
    expect(api.extractAttachmentUrl).not.toHaveBeenCalled();
    expect(result.current.attachments).toEqual([]);
  });

  it('ignores pending URL results after the URL policy is withdrawn', async () => {
    const pending = deferred<typeof extracted>();
    vi.mocked(api.extractAttachmentUrl).mockReturnValue(pending.promise);
    const changed = vi.fn();
    const { result, rerender } = renderHook(({ allowed }) =>
      useComposerAttach(changed, false, { allowUrlExtraction: allowed }), { initialProps: { allowed: true } });
    act(() => result.current.onPaste({ clipboardData: { files: [], getData: () => 'https://example.com/source' } } as never));
    rerender({ allowed: false });
    rerender({ allowed: true });
    await act(async () => { pending.resolve(extracted); await pending.promise; });
    expect(result.current.attachments).toEqual([]);
    expect(changed).not.toHaveBeenCalled();
    expect(result.current.busy).toBe(false);
  });

  it('keeps concurrent files and stays busy until both finish', async () => {
    const first = deferred<typeof extracted>();
    const second = deferred<typeof extracted>();
    vi.mocked(api.extractAttachmentFile).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => useComposerAttach(vi.fn()));
    let a!: Promise<void>, b!: Promise<void>;
    act(() => { a = result.current.addFiles([doc('a.txt')]); b = result.current.addFiles([doc('b.txt')]); });
    await act(async () => { second.resolve(extracted); await b; });
    expect(result.current.busy).toBe(true);
    await act(async () => { first.resolve(extracted); await a; });
    expect(result.current.attachments.map(item => item.name).sort()).toEqual(['a.txt', 'b.txt']);
    expect(result.current.busy).toBe(false);
  });

  it('does not resurrect an image removed while preparation is pending', async () => {
    const pending = deferred<Awaited<ReturnType<typeof fileToImagePayload>>>();
    vi.mocked(fileToImagePayload).mockReturnValue(pending.promise);
    const { result } = renderHook(() => useComposerAttach(vi.fn()));
    let adding!: Promise<void>;
    act(() => { adding = result.current.addFiles([new File(['x'], 'shot.png', { type: 'image/png' })]); });
    act(() => result.current.removeAt(0));
    await act(async () => { pending.resolve({ name: 'shot.png', mime_type: 'image/png', data: 'eA==' }); await adding; });
    expect(result.current.attachments).toEqual([]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:synthetic');
  });

  it('clear invalidates an in-flight batch including files not started yet', async () => {
    const pending = deferred<typeof extracted>();
    vi.mocked(api.extractAttachmentFile).mockReturnValue(pending.promise);
    const { result } = renderHook(() => useComposerAttach(vi.fn()));
    let adding!: Promise<void>;
    act(() => { adding = result.current.addFiles([doc('a.txt'), doc('b.txt')]); });
    act(() => result.current.clear());
    await act(async () => { pending.resolve(extracted); await adding; });
    expect(result.current.attachments).toEqual([]);
    expect(api.extractAttachmentFile).toHaveBeenCalledTimes(1);
    expect(result.current.busy).toBe(false);
  });

  it('does not notify a departed composer after unmount', async () => {
    const pending = deferred<typeof extracted>();
    vi.mocked(api.extractAttachmentFile).mockReturnValue(pending.promise);
    const changed = vi.fn();
    const { result, unmount } = renderHook(() => useComposerAttach(changed));
    let adding!: Promise<void>;
    act(() => { adding = result.current.addFiles([doc('a.txt')]); });
    unmount();
    await act(async () => { pending.resolve(extracted); await adding; });
    expect(changed).not.toHaveBeenCalled();
  });

  it('merges an overlapping URL and file extraction', async () => {
    const url = deferred<typeof extracted>();
    const file = deferred<typeof extracted>();
    vi.mocked(api.extractAttachmentUrl).mockReturnValue(url.promise);
    vi.mocked(api.extractAttachmentFile).mockReturnValue(file.promise);
    const { result } = renderHook(() => useComposerAttach(vi.fn()));
    let adding!: Promise<void>;
    act(() => {
      result.current.onPaste({ clipboardData: { files: [], getData: () => 'https://example.com/source' } } as never);
      adding = result.current.addFiles([doc('a.txt')]);
    });
    await act(async () => { file.resolve(extracted); await adding; });
    expect(result.current.busy).toBe(true);
    await act(async () => { url.resolve(extracted); await url.promise; });
    expect(result.current.attachments.map(item => item.name)).toEqual(['a.txt', 'https://example.com/source']);
    expect(result.current.busy).toBe(false);
  });

  it('reserves pending document slots across concurrent batches', async () => {
    const pending = deferred<typeof extracted>();
    vi.mocked(api.extractAttachmentFile).mockReturnValue(pending.promise);
    const { result } = renderHook(() => useComposerAttach(vi.fn()));
    const work: Promise<void>[] = [];
    act(() => {
      for (let index = 0; index < 10; index++) work.push(result.current.addFiles([doc(`${index}.txt`)]));
    });
    expect(api.extractAttachmentFile).toHaveBeenCalledTimes(9);
    expect(result.current.error).toBe('attach.too_many');
    await act(async () => { pending.resolve(extracted); await Promise.all(work); });
    expect(result.current.attachments).toHaveLength(9);
    expect(result.current.busy).toBe(false);
  });

  it('an old completion cannot finish or replace the new batch after clear', async () => {
    const old = deferred<typeof extracted>();
    const fresh = deferred<typeof extracted>();
    vi.mocked(api.extractAttachmentFile).mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const { result } = renderHook(() => useComposerAttach(vi.fn()));
    let before!: Promise<void>, after!: Promise<void>;
    act(() => { before = result.current.addFiles([doc('old.txt')]); });
    act(() => result.current.clear());
    act(() => { after = result.current.addFiles([doc('new.txt')]); });
    await act(async () => { old.resolve(extracted); await before; });
    expect(result.current.busy).toBe(true);
    expect(result.current.attachments).toEqual([]);
    await act(async () => { fresh.resolve(extracted); await after; });
    expect(result.current.attachments.map(item => item.name)).toEqual(['new.txt']);
    expect(result.current.busy).toBe(false);
  });

  it('unmount releases only unsent image previews', async () => {
    vi.mocked(fileToImagePayload).mockResolvedValue({ name: 'shot.png', mime_type: 'image/png', data: 'eA==' });
    const { result, unmount } = renderHook(() => useComposerAttach(vi.fn()));
    await act(async () => { await result.current.addFiles([new File(['x'], 'shot.png', { type: 'image/png' })]); });
    act(() => result.current.clear({ revokeUrls: false }));
    unmount();
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  });
});
