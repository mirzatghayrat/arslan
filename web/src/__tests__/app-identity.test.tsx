import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getVersion } from '@tauri-apps/api/app';
import { updaterAvailable } from '../lib/updater';
import { identitySummary, readAppIdentity } from '../lib/appIdentity';
import AppIdentityCard from '../components/settings/AppIdentityCard';
import en from '../locales/en.json';
import zh from '../locales/zh.json';
import ja from '../locales/ja.json';
import es from '../locales/es.json';
import de from '../locales/de.json';
import fr from '../locales/fr.json';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';

vi.mock('@tauri-apps/api/app', () => ({ getVersion: vi.fn() }));
vi.mock('../lib/updater', () => ({ updaterAvailable: vi.fn() }));

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(updaterAvailable).mockReturnValue(true);
});

describe('running app identity', () => {
  it.each([
    ['0.1.40-beta.3', 'preview'], ['0.1.38', 'stable'],
    ['1.2.0-rc.1+build.2', 'preview'], ['1.2.0+build.2', 'stable'],
  ])('classifies %s without reading a backend version', async (version, channel) => {
    vi.mocked(getVersion).mockResolvedValue(version);
    expect(await readAppIdentity()).toEqual({ client: 'desktop', version, channel });
  });

  it('does not invoke native IPC in a browser or guess a desktop version', async () => {
    vi.mocked(updaterAvailable).mockReturnValue(false);
    expect(await readAppIdentity()).toEqual({ client: 'browser', version: null, channel: 'unknown' });
    expect(getVersion).not.toHaveBeenCalled();
  });

  it.each(['', '0.1.40\nsecret', 'arbitrary text', '01.2.3'])('fails closed on invalid metadata %j', async version => {
    vi.mocked(getVersion).mockResolvedValue(version);
    expect(await readAppIdentity()).toEqual({ client: 'desktop', version: null, channel: 'unknown' });
  });

  it('handles older shells without the read-only permission', async () => {
    vi.mocked(getVersion).mockRejectedValue(new Error('denied'));
    expect((await readAppIdentity()).channel).toBe('unknown');
  });

  it('exports only identity fields even if the input has additional private data', () => {
    const extra = { client: 'desktop' as const, version: '0.1.40-beta.3', channel: 'preview' as const,
      prompt: 'private prompt', key: 'private key', path: '/private/path' };
    expect(identitySummary(extra)).toBe('Arslan — app identity\nclient: desktop\nversion: 0.1.40-beta.3\nchannel: preview');
  });
});

async function show(locale = 'en') {
  const i18n = createInstance();
  await i18n.init({ lng: locale, fallbackLng: 'en', resources: Object.fromEntries(
    Object.entries({ en, zh, ja, es, de, fr }).map(([key, value]) => [key, { translation: value }]),
  ) });
  return render(<I18nextProvider i18n={i18n}><AppIdentityCard /></I18nextProvider>);
}

describe('identity display and previewable export', () => {
  it.each(Object.entries({ en, zh, ja, es, de, fr }))('shows preview instructions in %s', async (locale, messages) => {
    vi.mocked(getVersion).mockResolvedValue('0.1.40-beta.3');
    await show(locale);
    expect(await screen.findByText(`0.1.40-beta.3 · ${messages.appIdentity.preview}`)).toBeInTheDocument();
    expect(screen.getByText(messages.appIdentity.previewHint)).toBeInTheDocument();
  });

  it('copies only after a click and shows exactly the previewed summary', async () => {
    vi.mocked(getVersion).mockResolvedValue('0.1.40-beta.3');
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    await show();
    await screen.findByText('0.1.40-beta.3 · Preview');
    expect(writeText).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText(en.appIdentity.summary));
    const preview = screen.getByTestId('app-identity').querySelector('pre')!.textContent;
    fireEvent.click(screen.getByRole('button', { name: en.appIdentity.copy }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(preview));
    expect(await screen.findByText(en.appIdentity.copied)).toBeInTheDocument();
  });

  it('does not claim copying succeeded when clipboard access fails', async () => {
    vi.mocked(updaterAvailable).mockReturnValue(false);
    Object.defineProperty(navigator, 'clipboard', { configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
    await show();
    await screen.findByText(en.appIdentity.browser);
    fireEvent.click(screen.getByText(en.appIdentity.summary));
    fireEvent.click(screen.getByRole('button', { name: en.appIdentity.copy }));
    expect(await screen.findByText(en.appIdentity.copyFailed)).toBeInTheDocument();
    expect(screen.queryByText(en.appIdentity.copied)).not.toBeInTheDocument();
  });

  it('does not display a preview warning for stable or unreadable versions', async () => {
    vi.mocked(getVersion).mockResolvedValue('0.1.38');
    await show();
    await screen.findByText('0.1.38 · Stable');
    expect(screen.queryByText(en.appIdentity.previewHint)).not.toBeInTheDocument();
  });
});
