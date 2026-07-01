import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import MessageBody from '../components/MessageBody';

// i18n mock: titles render as their key so we can query by them.
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

const LONG = 'A meaningful sentence about the deliverable. '.repeat(12); // > EXPORT_MIN_CHARS (240)

describe('MessageBody action layers', () => {
  it('prose export row keeps its own Copy when there is NO message action row', () => {
    render(<MessageBody text={LONG} hasMessageActions={false} />);
    // export row present (copy + downloads)
    expect(screen.getByTitle('msg.copy')).toBeTruthy();
    expect(screen.getByTitle('msg.download_md')).toBeTruthy();
  });

  it('prose export row DROPS its Copy when the parent renders a message action row', () => {
    render(<MessageBody text={LONG} hasMessageActions={true} />);
    // no duplicate copy — the persistent 👍👎 copy 重新生成 row owns it now…
    expect(screen.queryByTitle('msg.copy')).toBeNull();
    // …but the export downloads stay.
    expect(screen.getByTitle('msg.download_md')).toBeTruthy();
    expect(screen.getByTitle('msg.download_html')).toBeTruthy();
  });

  const html = '<!doctype html><html><body><h1>Hello</h1></body></html>';

  it('HTML-doc card defers copy to the message row (no duplicate) but keeps preview + download', () => {
    render(<MessageBody text={html} hasMessageActions={true} />);
    // the card IS the whole message, so a card-copy would duplicate the row copy → dropped…
    expect(screen.queryByTitle('msg.copy')).toBeNull();
    // …preview + download are the card's own distinct artifact ops, always present.
    expect(screen.getByTitle('msg.preview')).toBeTruthy();
    expect(screen.getByTitle('msg.download_html')).toBeTruthy();
  });

  it('HTML-doc card keeps its own copy when there is NO message row (non-deliverable)', () => {
    render(<MessageBody text={html} hasMessageActions={false} />);
    expect(screen.getByTitle('msg.copy')).toBeTruthy();
    expect(screen.getByTitle('msg.preview')).toBeTruthy();
  });
});
