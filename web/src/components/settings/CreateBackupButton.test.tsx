import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import CreateBackupButton from './CreateBackupButton';
import { createBackup, shellAvailable } from '../../lib/shell';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('../../lib/shell', () => ({ createBackup: vi.fn(), shellAvailable: vi.fn() }));
beforeEach(() => { vi.mocked(shellAvailable).mockReturnValue(true); vi.mocked(createBackup).mockReset(); });
describe('native backup entry', () => {
  it('requests native confirmation without arbitrary paths or automatic retry', async () => {
    vi.mocked(createBackup).mockResolvedValue(false);
    render(<CreateBackupButton />);
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    expect(createBackup).toHaveBeenCalledExactlyOnceWith();
  });
  it('does not expose a nonfunctional browser button', () => {
    vi.mocked(shellAvailable).mockReturnValue(false);
    render(<CreateBackupButton />);
    expect(screen.queryByRole('button')).toBeNull();
  });
});
