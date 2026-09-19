import { cleanup, render } from '@testing-library/react';
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
