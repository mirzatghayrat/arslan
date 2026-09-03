/**
 * The conversation-mode button: one click to start listening, one to stop.
 * Toggled rather than held (the point of the mode), so the state is shown —
 * a pulsing pill while listening, a muted marker while a reply is read.
 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import { Mic, MicOff, Loader2 } from 'lucide-react';
import type { ConversationPhase } from '../hooks/useConversationMode';

export interface ConversationToggleProps {
  active: boolean;
  phase: ConversationPhase;
  partial: string;
  onToggle: () => void;
  disabled?: boolean;
}

export default function ConversationToggle({ active, phase, partial, onToggle, disabled }: ConversationToggleProps) {
  const { t } = useTranslation();
  const label = active ? t('voice.conversationStop') : t('voice.conversationStart');
  return (
    <span className="flex items-center gap-2 min-w-0">
      <button
        type="button"
        data-testid="conversation-toggle"
        data-phase={phase}
        aria-pressed={active}
        aria-label={label}
        title={label}
        disabled={disabled}
        onClick={onToggle}
        className={[
          'flex items-center gap-1 px-2.5 py-1 rounded-full border text-[10px] font-mono transition-colors select-none',
          active ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:border-primary/40',
          disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
        ].join(' ')}
      >
        {phase === 'arming' ? <Loader2 className="w-3 h-3 animate-spin" />
          : phase === 'muted' ? <MicOff className="w-3 h-3" />
          : <Mic className="w-3 h-3" />}
        {phase === 'listening' && <span>{t('voice.listening')}</span>}
        {phase === 'muted' && <span>{t('voice.speaking')}</span>}
      </button>
      {partial && (
        <span data-testid="conversation-partial" className="truncate text-[11px] text-muted-foreground font-sans">
          {partial}
        </span>
      )}
    </span>
  );
}
