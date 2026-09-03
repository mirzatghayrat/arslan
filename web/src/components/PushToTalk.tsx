/**
 * Hold to talk.
 *
 * Held rather than toggled, on purpose: while the button is down the app is
 * listening and while it is up it is not, and that is legible without a state
 * indicator to misread. It also sidesteps echo entirely — nothing is being
 * spoken while you hold it — which is the hard part of always-on voice and is
 * deliberately not in this first step.
 *
 * The recognizer needs to be TOLD which language to expect; it does not detect
 * one. So the locale is its own setting rather than the interface language —
 * the reading-aloud feature took the interface language and gave an English
 * voice Chinese sentences, and someone reading an English UI while speaking
 * Chinese is the normal case here, not the edge case.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Mic, Loader2 } from 'lucide-react';
import { parseLine, errorMessage } from '../lib/voiceLine';
export { parseLine, errorMessage };   // push-to-talk.test.ts imports them from here

export interface PushToTalkProps {
  /** BCP-47 tag the recognizer should expect, e.g. "zh-CN". */
  locale: string;
  /** Live best-guess while held — shown, never sent. */
  onPartial: (text: string) => void;
  /** What it settled on once the button is released. */
  onFinal: (text: string) => void;
  /** A refusal or a missing device, in words the user can act on. */
  onError: (message: string) => void;
  disabled?: boolean;
}

export default function PushToTalk({
  locale,
  onPartial,
  onFinal,
  onError,
  disabled,
}: PushToTalkProps) {
  const { t } = useTranslation();
  const [held, setHeld] = useState(false);
  const [arming, setArming] = useState(false);
  const holdingRef = useRef(false);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    (async () => {
      const tauri = (window as any).__TAURI__;
      if (!tauri?.event?.listen) return;
      const un = await tauri.event.listen('voice://line', (e: { payload: string }) => {
        const line = parseLine(e.payload);
        if (!line) return;
        if (line.t === 'ready') setArming(false);
        else if (line.t === 'partial') onPartial(line.text);
        else if (line.t === 'final') {
          setArming(false);
          onFinal(line.text);
        } else if (line.t === 'error') {
          setArming(false);
          setHeld(false);
          holdingRef.current = false;
          onError(errorMessage(line.code, line.msg, t));
        }
      });
      if (cancelled) un();
      else unlisten = un;
    })();
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [onPartial, onFinal, onError, t]);

  const press = useCallback(async () => {
    if (disabled || holdingRef.current) return;
    holdingRef.current = true;
    setHeld(true);
    setArming(true);
    try {
      await (window as any).__TAURI__?.core?.invoke('voice_start', { locale });
    } catch (e) {
      holdingRef.current = false;
      setHeld(false);
      setArming(false);
      onError(String(e));
    }
  }, [disabled, locale, onError]);

  const release = useCallback(async () => {
    if (!holdingRef.current) return;
    holdingRef.current = false;
    setHeld(false);
    try {
      await (window as any).__TAURI__?.core?.invoke('voice_stop');
    } catch {
      /* the helper exits on its own when our stdin closes */
    }
  }, []);

  // Releasing outside the button still counts as letting go, otherwise the
  // microphone stays open when the pointer drifts off while speaking.
  useEffect(() => {
    if (!held) return;
    const up = () => void release();
    window.addEventListener('mouseup', up);
    window.addEventListener('blur', up);
    return () => {
      window.removeEventListener('mouseup', up);
      window.removeEventListener('blur', up);
    };
  }, [held, release]);

  return (
    <button
      type="button"
      data-testid="push-to-talk"
      data-held={held ? 'true' : 'false'}
      aria-label={t('voice.holdToTalk')}
      title={`${t('voice.holdToTalk')} · ${locale}`}
      disabled={disabled}
      onMouseDown={() => void press()}
      onMouseUp={() => void release()}
      className={[
        'flex items-center gap-1 px-2.5 py-1 rounded-full border text-[10px] font-mono transition-colors select-none',
        held
          ? 'border-primary bg-primary/10 text-primary'
          : 'border-border text-muted-foreground hover:border-primary/40',
        disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
      ].join(' ')}
    >
      {arming ? <Loader2 className="w-3 h-3 animate-spin" /> : <Mic className="w-3 h-3" />}
      {held && <span>{t('voice.listening')}</span>}
    </button>
  );
}
