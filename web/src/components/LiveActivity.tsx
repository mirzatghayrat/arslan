import { useEffect, useState } from 'react';
import { RefreshCcw, Check, X, Asterisk } from 'lucide-react';
import WorkingPulse from './WorkingPulse';
import type { ToolStep } from '../api/client.types';

/**
 * LiveActivity — the "never a void" block (Claude-Code-style progress group).
 * While a turn is running it shows, live:
 *   • each tool step as it happens (spinner → ✓/✗ + result summary),
 *   • a scramble-text phase line (WorkingPulse),
 *   • an elapsed timer + tool-call count footer.
 * Data comes from the frames we already stream (tool_call/tool_result); this only renders it
 * live instead of waiting for stream_end to fold it into the message.
 */
function fmtElapsed(startedAt: number | null, now: number): string {
  if (!startedAt) return '0s';
  const s = Math.max(0, Math.floor((now - startedAt) / 1000));
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
}

export default function LiveActivity({
  steps,
  startedAt,
  phrases,
}: {
  steps: ToolStep[];
  startedAt: number | null;
  phrases: string[];
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div className="space-y-2 max-w-xl" data-testid="live-activity">
      {steps.length > 0 && (
        <div className="border border-border/60 bg-surface/40 rounded-xl px-3 py-2 space-y-1">
          {steps.map((s, i) => (
            <div key={i} className="flex items-center gap-2 text-[10.5px] font-mono min-w-0">
              {s.status === 'running'
                ? <RefreshCcw className="w-3 h-3 text-primary animate-spin shrink-0" />
                : s.status === 'ok'
                ? <Check className="w-3 h-3 text-success shrink-0" />
                : <X className="w-3 h-3 text-danger shrink-0" />}
              <span className="text-foreground shrink-0">{s.tool}</span>
              <span className="text-subtle-foreground truncate">
                {s.status === 'running' ? s.argsSummary : (s.resultSummary || s.argsSummary)}
              </span>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2 pl-1">
        <Asterisk className="w-3.5 h-3.5 text-primary animate-pulse shrink-0" />
        <WorkingPulse className="text-[11px] text-muted-foreground" phrases={phrases} />
        <span className="text-[10px] font-mono text-subtle-foreground shrink-0">
          · {fmtElapsed(startedAt, now)}
          {steps.length > 0 ? ` · ${steps.length} tool call${steps.length > 1 ? 's' : ''}` : ''}
        </span>
      </div>
    </div>
  );
}
