/**
 * toolHumanize — the single source of natural-language wording for tool activity.
 *
 * Shared by LiveActivity (in-flight steps) AND the finished-message tool cards
 * (ToolActivityCard) so the phrasing never diverges (user feedback: finished cards
 * read as `Standard Executor tool render_deck: OK` + a raw JSON wall while the live
 * view already narrated 搜索「query」/ 生成 PPT).
 *
 * All strings go through i18n via the caller-provided `t` (activity.* keys).
 */
import type { ToolStep } from '../api/client.types';

export type TranslateFn = (k: string, o?: Record<string, unknown>) => string;

/** Best-effort pull of a human-meaningful bit out of the raw argsSummary JSON. */
function argBit(argsSummary: string | undefined, key: string): string {
  if (!argsSummary) return '';
  try {
    const v = JSON.parse(argsSummary)?.[key];
    return typeof v === 'string' ? v : '';
  } catch { return ''; }
}

function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
}

/**
 * Natural-language step line (user feedback: raw `web_search 5 results` ×5 plus internal
 * error strings read as noise — mature products narrate). Each step becomes a short verb
 * phrase carrying the one argument a human cares about (the query / the site), and failures
 * get a calm one-liner instead of the backend's internal error text.
 */
export function humanizeStep(
  s: Pick<ToolStep, 'tool' | 'argsSummary' | 'resultSummary' | 'status'>,
  t: TranslateFn,
): string {
  const q = argBit(s.argsSummary, 'query');
  const host = hostOf(argBit(s.argsSummary, 'url'));
  switch (s.tool) {
    case 'web_search':
      return s.status === 'error'
        ? t('activity.search_fail')
        : t('activity.search', { q: q ? `「${q.slice(0, 40)}」` : '' });
    case 'web_extract':
      return s.status === 'error'
        ? t('activity.read_fail')
        : t('activity.read', { host: host || '…' });
    case 'render_deck':
      return s.status === 'error' ? t('activity.deck_fail') : t('activity.deck');
    case 'render_chart':
      return s.status === 'error' ? t('activity.chart_fail') : t('activity.chart');
    case 'run_python':
      return s.status === 'error' ? t('activity.code_fail') : t('activity.code');
    default:
      // Unknown tool: keep the tool name + short summary rather than inventing a verb.
      return `${s.tool} ${s.status === 'running' ? (s.argsSummary ?? '') : (s.resultSummary ?? '')}`.slice(0, 60);
  }
}

/**
 * Plain-words outcome for a FINISHED, successful step ("5 条结果" / "已生成 PPTX · 14 页").
 * The backend resultSummary is internal shorthand ("5 results", "12345 chars extracted",
 * "ok") — recognizable patterns are re-said through i18n; anything else short passes
 * through as-is (it may already be a human sentence from the executor).
 */
export function humanizeOutcome(
  s: { tool: string; resultSummary?: string; slides?: number },
  t: TranslateFn,
): string {
  const raw = (s.resultSummary ?? '').trim();
  if (s.tool === 'render_deck' && s.slides != null && s.slides > 0) {
    return t('activity.deck_done', { slides: s.slides });
  }
  if (s.tool === 'render_chart') return t('activity.chart_done');
  const nResults = raw.match(/^(\d+) results$/);
  if (nResults) return t('activity.n_results', { count: Number(nResults[1]) });
  const nChars = raw.match(/^(\d+) chars extracted$/);
  if (nChars) return t('activity.n_chars', { count: Number(nChars[1]) });
  if (!raw || raw === 'ok') return t('activity.done');
  return raw.slice(0, 80);
}
