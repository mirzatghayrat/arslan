/**
 * ToolActivityCard — the finished-message tool activity block (all layout variants).
 *
 * User feedback: the old cards read `Standard Executor tool render_deck: OK` followed
 * by a raw JSON args wall. Now the headline is the SAME natural language as the live
 * view (lib/toolHumanize, i18n activity.* keys) with an honest ✓/✗ and a plain-words
 * outcome ("5 条结果" / "已生成 PPTX · 14 页"); the raw args/result strings move behind
 * a small collapsed 详情 toggle (default collapsed).
 *
 * Artifact cards (EChart / SVG / DeckDownloadCard) are kept exactly as before and
 * stay always visible — only the raw text plumbing is folded away.
 */
import { useState } from 'react';
import { Check, X, ChevronRight, ChevronDown } from 'lucide-react';
import MatrixSpinner from './MatrixSpinner';
import { useTranslation } from 'react-i18next';
import type { ToolActivity } from '../types';
import { humanizeStep, humanizeOutcome, provenanceFromSummary } from '../lib/toolHumanize';
import EChart from './EChart';
import DeckDownloadCard from './DeckDownloadCard';

export default function ToolActivityCard({ activity }: { activity: ToolActivity }) {
  const { t } = useTranslation();
  const [showDetails, setShowDetails] = useState(false);
  // stepStatus carries the raw ok/error; older items without it degrade to ok-when-completed.
  const status = activity.stepStatus ?? (activity.status === 'running' ? 'running' : 'ok');
  const headline = humanizeStep(
    { tool: activity.toolName, argsSummary: activity.action, resultSummary: activity.outputSummary, status },
    t,
  );
  // Who served this. Empty for every tool but web_search, and for a search whose
  // result predates provenance — an absent marker renders nothing rather than
  // guessing.
  const provenance = activity.toolName === 'web_search' && status === 'ok'
    ? provenanceFromSummary(activity.outputSummary, t)
    : '';
  const outcome = status === 'ok'
    ? humanizeOutcome(
        { tool: activity.toolName, resultSummary: activity.outputSummary, slides: activity.artifactPptx?.slides },
        t,
      )
    : '';

  return (
    <div
      data-testid="tool-activity-card"
      className="border border-border/60 bg-surface/40 rounded-xl px-3 py-2.5 space-y-2 max-w-xl text-[11px] font-sans"
    >
      {/* Humanized headline: verb phrase + honest ✓/✗ + plain-words outcome */}
      <div className="flex items-center gap-2 min-w-0">
        {status === 'running'
          ? <MatrixSpinner size={14} className="text-primary shrink-0" />
          : status === 'error'
          ? <X className="w-3.5 h-3.5 text-danger shrink-0" />
          : <Check className="w-3.5 h-3.5 text-success shrink-0" />}
        <span className={`truncate ${status === 'error' ? 'text-muted-foreground' : 'text-foreground'}`}>
          {headline}
        </span>
        {provenance && (
          <span
            data-testid="search-provenance"
            className="shrink-0 text-[10px] font-mono text-subtle-foreground"
          >
            {provenance}
          </span>
        )}
        {outcome && <span className="text-muted-foreground shrink-0">· {outcome}</span>}
      </div>

      {/* 🔒 SECURITY: artifactSvg/artifactChart/artifactPptx are populated ONLY from the backend
          render_chart/render_deck tool_result frame (arslanStore), NEVER from LLM message text.
          Do not render SVG from any other source. Artifact cards stay exactly as before. */}
      {activity.artifactChart && (
        <EChart option={activity.artifactChart} className="tool-chart" />
      )}
      {activity.artifactSvg && (
        <div className="tool-chart" dangerouslySetInnerHTML={{ __html: activity.artifactSvg }} />
      )}
      {activity.artifactPptx && (
        <DeckDownloadCard {...activity.artifactPptx} />
      )}

      {/* Raw args/result live behind a small collapsed 详情 toggle (default collapsed). */}
      {(activity.action || activity.outputSummary) && (
        <button
          type="button"
          onClick={() => setShowDetails((v) => !v)}
          className="flex items-center gap-1 text-[10px] font-mono text-subtle-foreground hover:text-primary transition-colors select-none"
        >
          {showDetails ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          {t('activity.details')}
        </button>
      )}
      {showDetails && (
        <div className="space-y-1.5 font-mono text-[10px]">
          {activity.action && (
            <div>
              <div className="text-subtle-foreground uppercase">{t('activity.args')}</div>
              <pre className="mt-0.5 bg-background/50 border border-border/50 rounded-lg p-2 whitespace-pre-wrap break-all text-muted-foreground">{activity.action}</pre>
            </div>
          )}
          {activity.outputSummary && (
            <div>
              <div className="text-subtle-foreground uppercase">{t('activity.result')}</div>
              <pre className="mt-0.5 bg-background/50 border border-border/50 rounded-lg p-2 whitespace-pre-wrap break-all text-muted-foreground">{activity.outputSummary}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
