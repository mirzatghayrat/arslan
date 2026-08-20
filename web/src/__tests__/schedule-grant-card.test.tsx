/**
 * The scheduling grant card (spec P2 §1.2, 裁决①).
 *
 * Like the workspace-write card this asks ONCE about a capability, so it
 * carries no "remember" checkbox. Unlike it, the thing being agreed to is a
 * RECURRING COST, so the card leads with the cadence — "every hour" is a very
 * different consent from "every morning", and a raw `every: 3600` does not
 * make that difference visible to someone deciding in one second.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

import ScheduleGrantCard, { humanCadence } from '../components/ScheduleGrantCard';

const base = { callId: 'sc1', name: 'morning CI', when: 'cron: 0 9 * * *' };

describe('humanCadence', () => {
  it('turns seconds into something a person can judge', () => {
    // The unit is what makes a cadence judgeable; a bare number is not.
    expect(humanCadence('every: 3600').toLowerCase()).toMatch(/hour|小时/);
    expect(humanCadence('every: 86400').toLowerCase()).toMatch(/day|天/);
    expect(humanCadence('every: 900').toLowerCase()).toMatch(/minute|分/);
    // …and the raw seconds never survive into what the user reads.
    for (const raw of ['3600', '86400', '900']) {
      expect(humanCadence(`every: ${raw}`)).not.toContain(raw);
    }
  });

  it('counts plural units so 6 hours cannot read as 6 seconds', () => {
    expect(humanCadence('every: 21600')).toBe('every 6 hours');
    expect(humanCadence('every: 172800')).toBe('every 2 days');
  });

  it('keeps a cron expression visible rather than guessing at it', () => {
    // Translating cron into prose invites a confident wrong reading; showing it
    // is honest, and the user who wrote it can read it.
    expect(humanCadence('cron: 0 9 * * *')).toContain('0 9 * * *');
  });

  it('passes through anything it does not recognise', () => {
    expect(humanCadence('weird')).toBe('weird');
  });
});

describe('ScheduleGrantCard', () => {
  it('shows the task name and the cadence', () => {
    render(<ScheduleGrantCard {...base} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    const card = screen.getByTestId('schedule-card');
    expect(card.textContent).toContain('morning CI');
    expect(card.textContent).toContain('0 9 * * *');
  });

  it('offers no remember checkbox — approval already lasts the session', () => {
    render(<ScheduleGrantCard {...base} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.queryByRole('checkbox')).toBeNull();
  });

  it('says that scheduled runs cannot write or execute', () => {
    /** The user is agreeing to unattended runs; what those runs CANNOT do is
     *  part of what makes the decision safe to make. */
    render(<ScheduleGrantCard {...base} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId('schedule-scope')).toBeTruthy();
  });

  it('confirm and cancel report the call id', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ScheduleGrantCard {...base} onConfirm={onConfirm} onCancel={onCancel} />);
    fireEvent.click(screen.getByTestId('schedule-allow'));
    expect(onConfirm).toHaveBeenCalledWith('sc1');
    fireEvent.click(screen.getByTestId('schedule-deny'));
    expect(onCancel).toHaveBeenCalledWith('sc1');
  });

  it('renders an interval cadence in human terms', () => {
    render(<ScheduleGrantCard {...base} when="every: 21600"
                              onConfirm={vi.fn()} onCancel={vi.fn()} />);
    const text = screen.getByTestId('schedule-card').textContent ?? '';
    expect(text.toLowerCase()).toMatch(/hour|小时/);
    expect(text).not.toContain('21600');     // the raw seconds are not the point
  });
});
