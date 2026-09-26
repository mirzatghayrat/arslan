import { render, screen, fireEvent } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Markdown from './Markdown';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
type ShellWindow = Window & { __TAURI_INTERNALS__?: { invoke: ReturnType<typeof vi.fn> } };
const win = window as ShellWindow;
afterEach(() => { delete win.__TAURI_INTERNALS__; });

describe('native Markdown source opening', () => {
  it('keeps normal browser link semantics without desktop shell', () => {
    render(<Markdown>{'[Source](https://example.org/)'}</Markdown>);
    expect(screen.getByRole('link').getAttribute('href')).toBe('https://example.org/');
    expect(screen.getByRole('link').getAttribute('rel')).toBe('noopener noreferrer');
  });
  it('routes a source click through the existing native gate', async () => {
    const invoke = vi.fn(async () => undefined);
    win.__TAURI_INTERNALS__ = { invoke };
    render(<Markdown>{'[Source](https://example.org/)'}</Markdown>);
    fireEvent.click(screen.getByRole('link'));
    expect(invoke).toHaveBeenCalledExactlyOnceWith('open_external', { url: 'https://example.org/' });
  });
  it.each(['http://example.org/', '//example.org/'])('surfaces a native refusal for %s', async href => {
    win.__TAURI_INTERNALS__ = { invoke: vi.fn(async () => { throw new Error('refused'); }) };
    render(<Markdown>{`[Source](${href})`}</Markdown>);
    fireEvent.click(screen.getByRole('link'));
    expect(await screen.findByRole('alert')).toHaveTextContent('externalLink.failed');
  });
});
