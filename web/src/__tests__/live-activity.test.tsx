import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import LiveActivity from '../components/LiveActivity';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

describe('LiveActivity', () => {
  it('renders live tool steps with status + elapsed footer', () => {
    render(
      <LiveActivity
        startedAt={Date.now() - 65_000}
        phrases={['working…']}
        steps={[
          { tool: 'web_search', argsSummary: '{"query":"OKX"}', status: 'ok', resultSummary: '5 results' },
          { tool: 'render_deck', argsSummary: '{"slides":…}', status: 'running' },
        ]}
      />,
    );
    expect(screen.getByText('web_search')).toBeTruthy();
    expect(screen.getByText('5 results')).toBeTruthy();        // finished step shows result
    expect(screen.getByText('render_deck')).toBeTruthy();      // running step visible immediately
    expect(screen.getByText(/1m 5s · 2 tool calls/)).toBeTruthy();  // timer + count footer
  });

  it('shows just the pulse footer before any tool fires (no empty box)', () => {
    const { container } = render(<LiveActivity startedAt={Date.now()} phrases={['thinking…']} steps={[]} />);
    expect(screen.getByText(/0s/)).toBeTruthy();
    expect(container.querySelectorAll('.border').length).toBe(0);  // no steps → no steps box
  });
});
