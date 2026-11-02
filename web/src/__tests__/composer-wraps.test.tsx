// SMART (the user, 2026-11-02): the chat input wraps and grows with what is typed, up to a cap (12 lines or 40% of
// the window, whichever is smaller), then scrolls inside. Enter sends and Shift+Enter starts a new line, as before;
// an Enter that confirms an input method's composition (Chinese, Japanese) only confirms it. Both composers.
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { useState } from 'react';
import OrchestratorChat from '../components/OrchestratorChat';
import { ComposerInput, MAX_LINES } from '../components/ComposerInput';
import type { Message } from '../types';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock('../api/client', () => ({ api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));

const LINE = 20;                                   // px, as the tests style the box

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
  // jsdom lays nothing out: a textarea's content is as tall as its lines, and as in a browser its scrollHeight is
  // never less than the height it was given, so a box that is not reset before it is measured never shrinks.
  Object.defineProperty(HTMLTextAreaElement.prototype, 'scrollHeight', {
    configurable: true, get() {
      const el = this as HTMLTextAreaElement;
      return Math.max(el.value.split('\n').length * LINE, parseFloat(el.style.height) || 0);
    },
  });
});

let innerHeight: number;
beforeEach(() => { innerHeight = window.innerHeight; window.innerHeight = 2000; });
afterEach(() => { window.innerHeight = innerHeight; });

function Box({ initial = '', onSend = vi.fn() }: { initial?: string; onSend?: () => void }) {
  const [value, setValue] = useState(initial);
  return <ComposerInput aria-label="box" value={value} onChange={(e) => setValue(e.target.value)} onSend={onSend}
    style={{ lineHeight: `${LINE}px`, paddingTop: '0px', paddingBottom: '0px' }} />;
}

const lines = (n: number) => Array.from({ length: n }, (_, i) => `line ${i + 1}`).join('\n');
const box = () => screen.getByLabelText('box') as HTMLTextAreaElement;

describe('ComposerInput', () => {
  it('is a textarea, so long text wraps instead of running on one line', () => {
    render(<Box />);
    expect(box().tagName).toBe('TEXTAREA');
    expect(box().getAttribute('wrap')).not.toBe('off');
  });

  it('grows with its content and does not scroll while under the cap', () => {
    render(<Box />);
    fireEvent.change(box(), { target: { value: lines(5) } });
    expect(box().style.height).toBe(`${5 * LINE}px`);
    expect(box().style.overflowY).toBe('hidden');
  });

  it(`stops at ${MAX_LINES} lines and scrolls inside past them`, () => {
    render(<Box />);
    fireEvent.change(box(), { target: { value: lines(40) } });
    expect(box().style.height).toBe(`${MAX_LINES * LINE}px`);
    expect(box().style.overflowY).toBe('auto');
  });

  it('stops at 40% of the window when that is smaller', () => {
    window.innerHeight = 400;                      // 40% = 160px, less than 12 lines (240px)
    render(<Box />);
    fireEvent.change(box(), { target: { value: lines(40) } });
    expect(box().style.height).toBe('160px');
    expect(box().style.overflowY).toBe('auto');
  });

  it('shrinks back when text is deleted', () => {
    render(<Box initial={lines(9)} />);
    expect(box().style.height).toBe(`${9 * LINE}px`);
    fireEvent.change(box(), { target: { value: 'one line' } });
    expect(box().style.height).toBe(`${LINE}px`);
  });

  it('measures the cap again when the window is resized', () => {
    render(<Box initial={lines(40)} />);
    expect(box().style.height).toBe(`${MAX_LINES * LINE}px`);
    window.innerHeight = 300;                      // 40% = 120px
    fireEvent(window, new Event('resize'));
    expect(box().style.height).toBe('120px');
  });

  it('sends on Enter', () => {
    const onSend = vi.fn();
    render(<Box initial="hello" onSend={onSend} />);
    const ev = fireEvent.keyDown(box(), { key: 'Enter' });
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(ev).toBe(false);                        // the default (a new line) is prevented
  });

  it('starts a new line on Shift+Enter, without sending', () => {
    const onSend = vi.fn();
    render(<Box initial="hello" onSend={onSend} />);
    expect(fireEvent.keyDown(box(), { key: 'Enter', shiftKey: true })).toBe(true);
    expect(onSend).not.toHaveBeenCalled();
  });

  it.each([['isComposing', { isComposing: true }], ['keyCode 229 (WebKit)', { keyCode: 229 }]])(
    'an Enter that confirms an input method composition (%s) does not send', (_, init) => {
      const onSend = vi.fn();
      render(<Box initial="nihao" onSend={onSend} />);
      fireEvent.keyDown(box(), { key: 'Enter', ...init });
      expect(onSend).not.toHaveBeenCalled();
    });
});

const history: Message[] = [
  { id: 'm1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
];
const props = { setChatHistory: vi.fn(), spawns: [], currentStyle: 'quartz' as const, setCurrentStyle: vi.fn(),
  activeThread: null };

describe('both composers', () => {
  it('the conversation composer is a growing textarea: Enter sends, Shift+Enter does not', () => {
    const onSendMessage = vi.fn();
    const { container } = render(<OrchestratorChat {...props} chatHistory={history} onSendMessage={onSendMessage} />);
    const input = container.querySelector('#chat-message-input') as HTMLTextAreaElement;
    expect(input.tagName).toBe('TEXTAREA');
    fireEvent.change(input, { target: { value: 'first line\nsecond line' } });
    expect(input.style.height).not.toBe('');
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(onSendMessage).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSendMessage).toHaveBeenCalledWith('first line\nsecond line', undefined);
  });

  it('the conversation composer sends nothing on Enter while it is blank', () => {
    const onSendMessage = vi.fn();
    const { container } = render(<OrchestratorChat {...props} chatHistory={history} onSendMessage={onSendMessage} />);
    const input = container.querySelector('#chat-message-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: '   \n ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('the conversation composer does not send on an Enter that confirms a composition', () => {
    const onSendMessage = vi.fn();
    const { container } = render(<OrchestratorChat {...props} chatHistory={history} onSendMessage={onSendMessage} />);
    const input = container.querySelector('#chat-message-input') as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: 'ni hao' } });
    fireEvent.keyDown(input, { key: 'Enter', keyCode: 229 });
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('the first message composer grows too, from its three lines', () => {
    const onSendMessage = vi.fn();
    const { container } = render(<OrchestratorChat {...props} chatHistory={[]} onSendMessage={onSendMessage} />);
    const input = container.querySelector('#landing-message-input') as HTMLTextAreaElement;
    expect(input.tagName).toBe('TEXTAREA');
    expect(input.rows).toBe(3);
    fireEvent.change(input, { target: { value: lines(6) } });
    expect(input.style.height).not.toBe('');
    fireEvent.keyDown(input, { key: 'Enter', keyCode: 229 });
    expect(onSendMessage).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSendMessage).toHaveBeenCalledWith(lines(6), undefined);
  });
});
