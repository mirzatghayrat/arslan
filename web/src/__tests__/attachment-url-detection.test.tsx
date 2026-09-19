import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useComposerAttach } from '../components/ComposerAttach';
import { api } from '../api/client';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('../api/client', () => ({ api: { extractAttachmentUrl: vi.fn() } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it.each([
  ['http://127.0.0.1/', 'http://127.0.0.1/'],
  ['http://169.254.169.254/latest/meta-data/', 'http://169.254.169.254/latest/meta-data/'],
  ['http://[::1]', 'http://[::1]'],
  ['(http://[::1]:8080/path).', 'http://[::1]:8080/path'],
  ['https://例子.测试/页面。', 'https://例子.测试/页面'],
  ['https://example.com/wiki/Example_(topic)', 'https://example.com/wiki/Example_(topic)'],
  ['(https://example.com/wiki/Example_(topic)).', 'https://example.com/wiki/Example_(topic)'],
  ['https://example.com/page?x=1#section', 'https://example.com/page?x=1#section'],
  ['https://example.com/source' + '],'.repeat(10000), 'https://example.com/source'],
])('routes explicit URL %s to the existing safe extraction endpoint', async (text, expected) => {
  // Rejection models the backend policy boundary; recognizing syntax must never
  // introduce direct fetch or turn a private address into an accepted source.
  vi.mocked(api.extractAttachmentUrl).mockRejectedValue(new Error('policy refusal'));
  const { result } = renderHook(() => useComposerAttach(vi.fn()));
  await act(async () => { result.current.onPaste({ clipboardData: { files: [], getData: () => text } } as never); });
  expect(api.extractAttachmentUrl).toHaveBeenCalledExactlyOnceWith(expected, false);
  expect(result.current.attachments).toEqual([]);
  expect(result.current.error).toBe('inputs.urlFailed');
});

it.each(['example.com', 'report.txt', 'file:///private/example.txt', 'javascript:alert(1)', 'https://', 'http://[broken]'])(
  'does not auto-extract invalid or non-web input %s', async text => {
    const { result } = renderHook(() => useComposerAttach(vi.fn()));
    await act(async () => { result.current.onPaste({ clipboardData: { files: [], getData: () => text } } as never); });
    expect(api.extractAttachmentUrl).not.toHaveBeenCalled();
  },
);

it('deduplicates repeated candidates even when extraction fails', async () => {
  vi.mocked(api.extractAttachmentUrl).mockRejectedValue(new Error('offline'));
  const { result } = renderHook(() => useComposerAttach(vi.fn()));
  await act(async () => { result.current.onPaste({ clipboardData: { files: [], getData: () =>
    'https://example.com/source https://example.com/source' } } as never); });
  expect(api.extractAttachmentUrl).toHaveBeenCalledTimes(1);
});
