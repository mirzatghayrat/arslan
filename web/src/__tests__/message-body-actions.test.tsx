import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import MessageBody from '../components/MessageBody';

// i18n mock: titles render as their key so we can query by them.
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

const SHORT = 'A quick conversational answer.'; // < COPY_MIN_CHARS (240)
const MEDIUM = 'A meaningful sentence about the deliverable. '.repeat(12); // ~552 chars: ≥ copy threshold, < LONG_CHARS
const LONG = 'A meaningful sentence about the deliverable. '.repeat(45); // ~2070 chars: > LONG_CHARS (1800) → boxed

describe('MessageBody action layers', () => {
  it('short reply gets NO row at all (no copy, no downloads)', () => {
    render(<MessageBody text={SHORT} hasMessageActions={false} />);
    expect(screen.queryByTitle('msg.copy')).toBeNull();
    expect(screen.queryByTitle('msg.download_md')).toBeNull();
    expect(screen.queryByTitle('msg.download_html')).toBeNull();
  });

  it('medium prose keeps its own Copy but NO downloads (boxed ⇔ downloadable)', () => {
    render(<MessageBody text={MEDIUM} hasMessageActions={false} />);
    // copy row present for messages without a message action row…
    expect(screen.getByTitle('msg.copy')).toBeTruthy();
    // …but downloads belong only to the long-output collapse box.
    expect(screen.queryByTitle('msg.download_md')).toBeNull();
    expect(screen.queryByTitle('msg.download_html')).toBeNull();
  });

  it('medium prose with a message action row renders NO export row at all', () => {
    render(<MessageBody text={MEDIUM} hasMessageActions={true} />);
    // copy is owned by the persistent 👍👎 copy 重新生成 row; downloads need the collapse box.
    expect(screen.queryByTitle('msg.copy')).toBeNull();
    expect(screen.queryByTitle('msg.download_md')).toBeNull();
  });

  it('long (boxed) prose gets the downloads, alongside the collapse toggle', () => {
    render(<MessageBody text={LONG} hasMessageActions={true} />);
    // the same LONG_CHARS condition drives the collapse box and the downloads
    expect(screen.getByText('msg.expand')).toBeTruthy();
    expect(screen.getByTitle('msg.download_md')).toBeTruthy();
    expect(screen.getByTitle('msg.download_html')).toBeTruthy();
    // no duplicate copy — the persistent message action row owns it
    expect(screen.queryByTitle('msg.copy')).toBeNull();
  });

  it('long (boxed) prose without a message action row keeps Copy + downloads', () => {
    render(<MessageBody text={LONG} hasMessageActions={false} />);
    expect(screen.getByTitle('msg.copy')).toBeTruthy();
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

describe("embedded HTML doc salvage (live incident: preamble + fence broke the card)", () => {
  const DOC = "<!DOCTYPE html><html><head><title>t</title><style>" + "x".repeat(400) +
    "</style></head><body>deck</body></html>";

  it("splits preamble prose + renders the doc card when the doc is fenced mid-message", () => {
    render(<MessageBody text={"以下是您需要的完整 HTML 代码:\n```html\n" + DOC + "\n```"} />);
    expect(screen.getByText(/以下是您需要的完整 HTML 代码/)).toBeTruthy();
    expect(screen.getByTestId("html-doc-card")).toBeTruthy();
  });

  it("does not salvage incomplete docs (no </html>)", () => {
    render(<MessageBody text={"讲解一下 <!DOCTYPE html><html><body>片段"} />);
    expect(screen.queryByTestId("html-doc-card")).toBeNull();
  });
});
