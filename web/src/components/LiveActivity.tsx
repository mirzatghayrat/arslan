import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import WorkingPulse from './WorkingPulse';
import MatrixSpinner from './MatrixSpinner';
import { StepLine } from './reply/ProcessList';
import { fromSteps, group, type ProcessItem } from '../lib/process';
import type { ToolStep } from '../api/client.types';

/** Only the latest lines show while working; the rest is one quiet "N earlier steps". */
export const LIVE_LINES = 6;

/** 0.1.59: this long without a new step, the row says a long answer can take a few minutes. */
export const LONG_QUIET_MS = 60_000;

/**
 * LiveActivity — the "never a void" block while a turn runs (0.1.58 §1).
 * Where the "…" was, and without a box: one line per step (plain words, ✓/✗, seconds),
 * Arslan's narration between them, reads and searches folded together, the latest few
 * shown — then the pulse line with the timer. When the turn ends this becomes the one
 * footer row under the answer (ReplyFooter), with the same words.
 * 0.1.59: the pulse line says only what is true — "Thinking…", and after a minute without a
 * new step "Still working — a long answer can take a few minutes" (no timed phrases).
 */
function fmtElapsed(startedAt: number | null, now: number): string {
  if (!startedAt) return '0s';
  const s = Math.max(0, Math.floor((now - startedAt) / 1000));
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
}

function GroupRow({ item }: { item: Extract<ProcessItem, { kind: 'group' }> }) {
  const { t } = useTranslation();
  return <div className="flex items-center gap-2 text-[12px]" data-testid="live-group">
    <span className="text-success" aria-hidden>✓</span>
    <span className="truncate">{t(`process.group_${item.family}`, { count: item.entries.length })}</span>
  </div>;
}

export default function LiveActivity({
  steps,
  startedAt,
  quietSince,
}: {
  steps: ToolStep[];
  startedAt: number | null;
  /** When the turn last moved (a step, a token); null = unknown, counts from startedAt. */
  quietSince?: number | null;
}) {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, []);
  const entries = fromSteps(steps);
  const items = group(entries);
  const hidden = Math.max(0, items.length - LIVE_LINES);
  const shown = items.slice(hidden);
  const calls = entries.filter((e) => e.kind === 'tool').length;
  const since = quietSince ?? startedAt;
  const label = t(since != null && now - since > LONG_QUIET_MS ? 'working.long' : 'working.thinking');

  return (
    <div className="flex max-w-xl flex-col gap-1.5" data-testid="live-activity">
      {hidden > 0 && <span className="text-[11px] text-subtle-foreground" data-testid="live-older">
        {t('process.older', { count: hidden })}</span>}
      {shown.map((item, i) => item.kind === 'note'
        ? <p key={i} className="text-[12px] leading-relaxed text-muted-foreground" data-testid="live-note">{item.text}</p>
        : item.kind === 'group' ? <GroupRow key={i} item={item} />
        : <StepLine key={i} entry={item} />)}
      <div className="flex items-center gap-2">
        <MatrixSpinner size={14} className="text-primary shrink-0" />
        <WorkingPulse className="text-[11px] text-muted-foreground" phrases={[label]} />
        <span className="text-[10px] font-mono text-subtle-foreground shrink-0">
          · {fmtElapsed(startedAt, now)}
          {calls > 0 ? ` · ${t('process.steps', { count: calls })}` : ''}
        </span>
      </div>
    </div>
  );
}
