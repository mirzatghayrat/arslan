import { act, renderHook } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import pack from '../../../evals/companion/stage2-inputs.json';
import { useComposerAttach, attachmentDelivery } from '../components/ComposerAttach';
import { api } from '../api/client';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('../api/client', () => ({ api: { extractAttachmentFile: vi.fn(), extractAttachmentUrl: vi.fn() } }));

beforeEach(() => vi.resetAllMocks());

it.each([
  ['unsupported', false], ['unsupported', true],
  ['invalid', false], ['invalid', true],
] as const)('S2-D4 retains usable input when %s input fails (bad first: %s)', async (failure, badFirst) => {
  const fixture = pack.cases.find(item => item.id === 'S2-D4');
  if (!fixture?.valid_text || !fixture.valid_filename || !fixture.unsupported_filename) {
    throw new Error('Frozen S2-D4 fixture missing');
  }
  const text = fixture.valid_text;
  vi.mocked(api.extractAttachmentFile).mockImplementation(async file => {
    if (file.name !== fixture.valid_filename) throw { detail: { code: 'inputs.invalid' } };
    return { text, chars: text.length, truncated: false };
  });
  const good = new File([text], fixture.valid_filename);
  const bad = new File(['unreadable'], failure === 'invalid' ? 'damaged.docx' : fixture.unsupported_filename);
  const { result } = renderHook(() => useComposerAttach(vi.fn()));
  await act(async () => { await result.current.addFiles(badFirst ? [bad, good] : [good, bad]); });
  expect(result.current.busy).toBe(false);
  expect(result.current.error).toBe(failure === 'invalid' ? 'inputs.invalid' : 'attach.unsupported');
  expect(result.current.attachments).toHaveLength(1);
  expect(result.current.attachments[0]).toMatchObject({ name: good.name, text });
  expect(attachmentDelivery(result.current.attachments, key => key).sources).toEqual([{ name: good.name, text }]);
  expect(api.extractAttachmentFile).toHaveBeenCalledTimes(failure === 'invalid' ? 2 : 1);
});
