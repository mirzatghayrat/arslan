import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { invoke } from '@tauri-apps/api/core';
import { shellAvailable } from '../lib/shell';
import { useIconStore } from '../stores/iconStore';
import IconPicker from '../components/settings/IconPicker';
import BrandMark from '../components/BrandMark';

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));
vi.mock('../lib/shell', () => ({ shellAvailable: vi.fn(() => false) }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  vi.mocked(shellAvailable).mockReturnValue(false);
  useIconStore.setState({ style: 'frosted', pending: false, error: false });
});
describe('icon preference', () => {
  it('updates all marks and persists the browser choice', async () => {
    render(<><IconPicker /><BrandMark /></>);
    fireEvent.click(screen.getByRole('radio', { name: 'settings.appIcon_monochrome' }));
    await waitFor(() => expect(screen.getByAltText('Arslan')).toHaveAttribute('src', '/brand/mark-monochrome.svg?v=20260923'));
    expect(localStorage.getItem('arslan_icon_style')).toBe('monochrome');
    expect(invoke).not.toHaveBeenCalled();
  });
  it('keeps the old selection if native update fails', async () => {
    vi.mocked(shellAvailable).mockReturnValue(true);
    vi.mocked(invoke).mockRejectedValueOnce(new Error('unavailable'));
    render(<IconPicker />);
    fireEvent.click(screen.getByRole('radio', { name: 'settings.appIcon_monochrome' }));
    expect(await screen.findByRole('alert')).toBeVisible();
    expect(screen.getByRole('radio', { name: 'settings.appIcon_frosted' })).toBeChecked();
    expect(localStorage.getItem('arslan_icon_style')).toBeNull();
  });
  it('restores native preference across a new sidecar origin', async () => {
    vi.mocked(shellAvailable).mockReturnValue(true);
    vi.mocked(invoke).mockResolvedValueOnce('monochrome');
    await useIconStore.getState().initialize();
    expect(useIconStore.getState().style).toBe('monochrome');
    expect(invoke).toHaveBeenCalledWith('get_app_icon');
  });
  it('serializes choices while the shell is applying one', async () => {
    vi.mocked(shellAvailable).mockReturnValue(true);
    let finish!: () => void;
    vi.mocked(invoke).mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
    const first = useIconStore.getState().select('monochrome');
    await useIconStore.getState().select('frosted');
    expect(invoke).toHaveBeenCalledTimes(1);
    expect(useIconStore.getState().style).toBe('frosted');
    finish(); await first;
    expect(useIconStore.getState().style).toBe('monochrome');
    expect(useIconStore.getState().pending).toBe(false);
  });
});
