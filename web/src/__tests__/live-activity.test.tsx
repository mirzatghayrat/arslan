import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import LiveActivity from '../components/LiveActivity';

// t mock with naive {{var}} interpolation so the natural-language lines are assertable.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, o?: Record<string, unknown>) => {
      const zh: Record<string, string> = {
        // 0.1.58 §1: steps read in process.* words; a failed page read keeps its calm activity.* line.
        'process.t_web_search_x': '搜了「{{x}}」',
        'activity.read_fail': '有个网页没打开,换个来源',
        'process.t_render_deck': '做了幻灯片',
        'process.steps': '{{count}} 步',
      };
      let s = zh[k] ?? k;
      for (const [key, v] of Object.entries(o ?? {})) s = s.replace(`{{${key}}}`, String(v));
      return s;
    },
  }),
}));

describe('LiveActivity', () => {
  it('renders tool steps as natural language (user feedback: no raw web_search spam)', () => {
    render(
      <LiveActivity
        startedAt={Date.now() - 65_000}
        quietSince={Date.now()}
        steps={[
          { tool: 'web_search', argsSummary: '{"query":"OKX 永续合约"}', status: 'ok', resultSummary: '5 results' },
          { tool: 'web_extract', argsSummary: '{"url":"https://x.test/a"}', status: 'error',
            resultSummary: 'fetch failed: http 403 — do not retry this URL' },
          { tool: 'render_deck', argsSummary: '{"slides":[]}', status: 'running' },
        ]}
      />,
    );
    expect(screen.getByText('搜了「OKX 永续合约」')).toBeTruthy();   // 0.1.58: the query, in plain words
    expect(screen.getByText('有个网页没打开,换个来源')).toBeTruthy(); // calm line, not the raw error
    expect(screen.queryByText(/http 403/)).toBeNull();                // internal error text never shown
    expect(screen.getByText('做了幻灯片')).toBeTruthy();              // running step visible immediately
    expect(screen.getByText(/1m 5s · 3 步/)).toBeTruthy();            // timer + count footer
  });

  it('shows just the pulse footer before any tool fires (no empty box)', () => {
    const { container } = render(<LiveActivity startedAt={Date.now()} steps={[]} />);
    expect(screen.getByText(/0s/)).toBeTruthy();
    expect(container.querySelectorAll('.border').length).toBe(0);  // no steps → no steps box
  });

  // 0.1.59 (run 160): the row cycled "Summoning specialist…", "Dispatching tools…" whatever was
  // happening. Now it says only what is true.
  it('says "Thinking…" while the turn moves, and that a long answer takes minutes after a quiet minute', () => {
    const { unmount } = render(<LiveActivity startedAt={Date.now() - 200_000} quietSince={Date.now() - 5_000} steps={[]} />);
    expect(screen.getByText('working.thinking')).toBeTruthy();
    expect(screen.queryByText('working.long')).toBeNull();
    unmount();
    render(<LiveActivity startedAt={Date.now() - 200_000} quietSince={Date.now() - 61_000} steps={[]} />);
    expect(screen.getByText('working.long')).toBeTruthy();
    expect(screen.queryByText(/working\.(summon|context|tools|compose)/)).toBeNull();
  });

  it('with no step time yet it counts the quiet from the start of the turn', () => {
    render(<LiveActivity startedAt={Date.now() - 61_000} steps={[]} />);
    expect(screen.getByText('working.long')).toBeTruthy();
  });
});
