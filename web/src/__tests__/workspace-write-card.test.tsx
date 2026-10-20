/**
 * The workspace-write grant card (spec 2026-08-20 P1 §1.5).
 *
 * Unlike the run_command card, this asks ONCE about a CAPABILITY, not about a
 * filename — so the card must name the DIRECTORY being granted, and must not
 * offer a "remember" checkbox: approving already means the rest of the session
 * (user ruling 2). The file that triggered it is shown as context only.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

import WorkspaceWriteCard from '../components/WorkspaceWriteCard';

const base = {
  callId: 'abc123',
  workspace: '/Users/me/Arslan Workspace',
  action: 'write_file',
  path: 'notes/plan.md',
};

describe('WorkspaceWriteCard', () => {
  it('names the directory being granted, not just the file', () => {
    render(<WorkspaceWriteCard {...base} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId('wswrite-card')).toBeTruthy();
    expect(screen.getByText('/Users/me/Arslan Workspace')).toBeTruthy();
    expect(screen.getByText(/notes\/plan\.md/)).toBeTruthy();
  });

  it('offers no remember checkbox — approval already lasts the session', () => {
    render(<WorkspaceWriteCard {...base} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.queryByRole('checkbox')).toBeNull();
  });

  it('confirm reports the call id and the scope, cancel the call id', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    // Every write card comes from permissions.decide, with its options (C2c removed the older card).
    const { rerender } = render(
      <WorkspaceWriteCard {...base} options={['once', 'conversation']} onConfirm={onConfirm} onCancel={onCancel} />);
    fireEvent.click(screen.getByTestId('wswrite-allow'));
    expect(onConfirm).toHaveBeenCalledWith('abc123', 'once');
    rerender(<WorkspaceWriteCard {...base} options={['once', 'conversation']} onConfirm={onConfirm} onCancel={onCancel} />);
    fireEvent.click(screen.getByTestId('wswrite-deny'));
    expect(onCancel).toHaveBeenCalledWith('abc123');
  });

  it('distinguishes an edit from a write in what it tells the user', () => {
    const { rerender } = render(
      <WorkspaceWriteCard {...base} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    const asWrite = screen.getByTestId('wswrite-card').textContent;
    rerender(<WorkspaceWriteCard {...base} action="edit_file"
                                 onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId('wswrite-card').textContent).not.toBe(asWrite);
  });
});
