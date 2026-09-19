import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import i18n from '../i18n';
import { AttachChips } from '../components/ComposerAttach';

afterEach(() => { cleanup(); void i18n.changeLanguage('en'); });
it.each([
  ['en', 'partially extracted'], ['zh', '仅部分提取'], ['ja', '一部のみ抽出'],
  ['es', 'extracción parcial'], ['de', 'teilweise extrahiert'], ['fr', 'extraction partielle'],
])('discloses partial extraction before sending in %s', async (language, label) => {
  await i18n.changeLanguage(language);
  const attachment = { name: 'source.pdf', kind: 'doc' as const, text: 'readable excerpt', chars: 16, truncated: true };
  const view = render(<AttachChips attachments={[attachment]} onRemove={vi.fn()} />);
  expect(view.container).toHaveTextContent(label);
  expect(view.container).toHaveTextContent('source.pdf');
  view.rerender(<AttachChips attachments={[{ ...attachment, truncated: false }]} onRemove={vi.fn()} />);
  expect(view.container).not.toHaveTextContent(label);
});

it.each(['en', 'zh', 'ja', 'es', 'de', 'fr'])('keeps video disclosure and removal separate from the filename in %s', async (language) => {
  await i18n.changeLanguage(language);
  const onRemove = vi.fn();
  const name = 'long-synthetic-video-source-with-cover.mp4';
  const view = render(<AttachChips attachments={[{
    name, text: 'metadata', chars: 8, truncated: false, kind: 'doc', inputKind: 'video',
    images: [{ name: 'frame', mime_type: 'image/png', data: 'cG5n' }],
  }]} onRemove={onRemove} />);
  const details = view.container.querySelector('.attach-chip__details')!;
  expect(details.querySelector('.attach-chip__name')).toHaveAttribute('title', name);
  expect(details.querySelector('.attach-chip__meta')).toHaveTextContent(i18n.t('inputs.videoSamples', { count: 1 }));
  const remove = view.getByRole('button', { name: i18n.t('ui.removeAttachment') });
  expect(details.contains(remove)).toBe(false);
  fireEvent.click(remove);
  expect(onRemove).toHaveBeenCalledWith(0);
});
