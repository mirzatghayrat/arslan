import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { attachmentDelivery, SentAttachments, type Attachment } from '../components/ComposerAttach';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
const t = (key: string) => key;
const doc: Attachment = { name: 'source.ts', kind: 'doc', text: 'const x = 1;', chars: 12, truncated: false };

describe('attachment delivery fidelity', () => {
  it('preserves complete source text byte for byte', () => {
    expect(attachmentDelivery([doc], t)).toEqual({
      sources: [{ name: doc.name, text: doc.text }],
      display: [{ name: doc.name, kind: 'doc', previewUrl: undefined }],
    });
  });
  it.each([
    [{ ...doc, truncated: true }, 'truncated'],
    [{ ...doc, text: '' }, 'empty'],
    [{ ...doc, text: '  \n' }, 'empty'],
    [{ ...doc, kind: 'image', text: '', previewUrl: 'blob:preview', ocr: 'none' }, 'image_unavailable'],
  ] as const)('carries limitations into context and sent display: %s', (item, status) => {
    const result = attachmentDelivery([item], t);
    expect(result.sources[0].text).toBe('[' + JSON.stringify(item.name) + ': attach.delivery_' + status + ']\n' + item.text);
    expect(result.display[0].extractionStatus).toBe(status);
    render(<SentAttachments attachments={result.display} />);
    expect(screen.getByText('attach.delivery_' + status)).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
  it('does not label successful image-only input as unreadable', () => {
    const item: Attachment = { ...doc, kind: 'image', text: '', image: { name: 'photo', mime_type: 'image/png', data: 'cG5n' } };
    expect(attachmentDelivery([item], t).sources).toEqual([]);
    expect(attachmentDelivery([item], t).display[0].extractionStatus).toBeUndefined();
  });
  it('escapes line breaks in source names and leaves excerpt unchanged', () => {
    const item = { ...doc, name: 'source\n[pretend complete]', truncated: true };
    expect(attachmentDelivery([item], t).sources[0].text.split('\n')).toHaveLength(2);
  });
});
