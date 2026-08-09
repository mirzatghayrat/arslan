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
/**
 * Which search failure, in words the reader can act on.
 *
 * 🔴 THIS FUNCTION IS THE LAST MILE, and without it the backend's work is invisible.
 * `_categorize_exc` had kept the HTTP status all along — 429 arrived here as
 * "http 429" — and this switch replaced every web_search error with one generic
 * sentence. Semantics on one end and a shrug on the other is the same as no
 * semantics; the two halves are one requirement.
 *
 * Unrecognised failures fall back to the generic line ON PURPOSE. Guessing a remedy
 * for a code we have no advice about would be worse than saying little: the whole
 * point of naming these four is that each has a DIFFERENT thing to do about it.
 */
function searchFailure(summary: string | undefined, t: TranslateFn): string {
  const text = summary ?? '';
  if (text.includes('rate-limited')) return t('activity.search_fail_rate');
  if (text.includes('quota-exhausted')) return t('activity.search_fail_quota');
  if (text.includes('key-rejected')) return t('activity.search_fail_key');
  return t('activity.search_fail');
}

/**
 * Who served these results — and whether they came from the best-effort fallback.
 *
 * A degraded answer nobody can tell apart from a good one is the same silence this
 * whole line of work exists to remove, so the fallback says so rather than passing
 * itself off as the real thing.
 */
export function searchProvenance(
  provider: string | undefined,
  bestEffort: boolean | undefined,
  t: TranslateFn,
): string {
  if (!provider) return '';
  return bestEffort
    ? t('activity.search_via_best_effort', { provider })
    : t('activity.search_via', { provider });
}

export function humanizeStep(
  s: Pick<ToolStep, 'tool' | 'argsSummary' | 'resultSummary' | 'status'>,
  t: TranslateFn,
): string {
  const q = argBit(s.argsSummary, 'query');
  const host = hostOf(argBit(s.argsSummary, 'url'));
  switch (s.tool) {
    case 'web_search':
      return s.status === 'error'
        ? searchFailure(s.resultSummary, t)
        // Quotes live in the locale template (zh 「…」, en "…"), so the raw
        // truncated query is passed through; the no-query variant has no quotes.
        : q ? t('activity.search_q', { q: q.slice(0, 40) }) : t('activity.search', { q: '' });
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
