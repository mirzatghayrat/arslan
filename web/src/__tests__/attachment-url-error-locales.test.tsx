import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import i18n from '../i18n';
import { api } from '../api/client';
import { useComposerAttach } from '../components/ComposerAttach';
import { inputMessages } from '../locales/inputs';

afterEach(async () => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); await i18n.changeLanguage('en'); });

it.each(['en', 'zh', 'ja', 'es', 'de', 'fr'] as const)(
  'localizes URL extraction failure without exposing transport details in %s', async language => {
    await i18n.changeLanguage(language);
    const extract = vi.spyOn(api, 'extractAttachmentUrl').mockRejectedValue(
      new Error('Connection refused to internal-host:1234?token=synthetic-secret'),
    );
    const changed = vi.fn();
    const { result } = renderHook(() => useComposerAttach(changed));
    await act(async () => {
      result.current.onPaste({ clipboardData: { files: [], getData: () => 'https://example.com/source' } } as never);
    });
    expect(extract).toHaveBeenCalledWith('https://example.com/source', false);
    expect(result.current.error).toBe(inputMessages[language].urlFailed);
    expect(result.current.error).not.toContain('internal-host');
    expect(result.current.error).not.toContain('synthetic-secret');
    expect(result.current.attachments).toEqual([]);
    expect(result.current.busy).toBe(false);
    expect(changed).not.toHaveBeenCalled();
  },
);

it('handles non-Error rejection values without rendering arbitrary objects', async () => {
  await i18n.changeLanguage('zh');
  vi.spyOn(api, 'extractAttachmentUrl').mockRejectedValue({ detail: { code: 'unknown-upstream-code' } });
  const { result } = renderHook(() => useComposerAttach(vi.fn()));
  await act(async () => {
    result.current.onPaste({ clipboardData: { files: [], getData: () => 'https://example.com/source' } } as never);
  });
  expect(result.current.error).toBe(inputMessages.zh.urlFailed);
  expect(result.current.busy).toBe(false);
});

it('retries a failed URL only when explicitly pasted again, not on every edit', async () => {
  vi.useFakeTimers();
  const extract = vi.spyOn(api, 'extractAttachmentUrl').mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue({ text: 'readable source', chars: 15, truncated: false });
  const { result } = renderHook(() => useComposerAttach(vi.fn()));
  const paste = { clipboardData: { files: [], getData: () => 'https://example.com/source' } } as never;
  await act(async () => { result.current.onPaste(paste); });
  expect(result.current.error).not.toBeNull();
  await act(async () => {
    result.current.onInputChange('https://example.com/source additional prompt ');
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(extract).toHaveBeenCalledTimes(1);
  await act(async () => { result.current.onPaste(paste); });
  expect(extract).toHaveBeenCalledTimes(2);
  expect(result.current.error).toBeNull();
  expect(result.current.attachments).toHaveLength(1);
  await act(async () => { result.current.onPaste(paste); });
  expect(extract).toHaveBeenCalledTimes(2);
});
