import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import HostRunResultButton from './HostRunResultButton';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

describe('durable host result entry', () => {
  it.each([undefined, null, -1, 0, 1.5, NaN])('does not link an invalid or temporary owner %s', runId => {
    render(<HostRunResultButton runId={runId} onOpen={vi.fn()} />);
    expect(screen.queryByRole('button')).toBeNull();
  });
  it('opens precisely the persisted run', () => {
    const open = vi.fn();
    render(<HostRunResultButton runId={7} onOpen={open} />);
    fireEvent.click(screen.getByRole('button', { name: 'replay.view_replay' }));
    expect(open).toHaveBeenCalledExactlyOnceWith(7);
  });
});
