import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import LiveActivity from '../components/LiveActivity';

// t mock with naive {{var}} interpolation so the natural-language lines are assertable.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k: string, o?: Record<string, unknown>) => {
      const zh: Record<string, string> = {
        'activity.search': '搜索 {{q}}',
        'activity.read_fail': '有个网页没打开,换个来源',
        'activity.deck': '生成 PPT',
        'activity.calls': '{{count}} 次工具调用',
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
        phrases={['working…']}
        steps={[
          { tool: 'web_search', argsSummary: '{"query":"OKX 永续合约"}', status: 'ok', resultSummary: '5 results' },
          { tool: 'web_extract', argsSummary: '{"url":"https://x.test/a"}', status: 'error',
            resultSummary: 'fetch failed: http 403 — do not retry this URL' },
          { tool: 'render_deck', argsSummary: '{"slides":[]}', status: 'running' },
        ]}
      />,
    );
    expect(screen.getByText('搜索 「OKX 永续合约」')).toBeTruthy();  // query surfaced, verb-first
    expect(screen.getByText('有个网页没打开,换个来源')).toBeTruthy(); // calm line, not the raw error
    expect(screen.queryByText(/http 403/)).toBeNull();                // internal error text never shown
    expect(screen.getByText('生成 PPT')).toBeTruthy();                // running step visible immediately
    expect(screen.getByText(/1m 5s · 3 次工具调用/)).toBeTruthy();    // timer + count footer
  });

  it('shows just the pulse footer before any tool fires (no empty box)', () => {
    const { container } = render(<LiveActivity startedAt={Date.now()} phrases={['thinking…']} steps={[]} />);
    expect(screen.getByText(/0s/)).toBeTruthy();
    expect(container.querySelectorAll('.border').length).toBe(0);  // no steps → no steps box
  });
});
