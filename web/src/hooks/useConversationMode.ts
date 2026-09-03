/**
 * Conversation mode's session with the shell.
 *
 * One helper process per enabled period. Everything it says arrives on
 * `voice://conv`; a final becomes `onFinal(text)` — which the caller turns
 * into an ordinary user message, the same call typing makes. Half-duplex:
 * while the Web Speech speaker is active (store `speaking`), the helper is
 * muted so the reply is not transcribed back into a question.
 */
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { parseLine, errorMessage } from '../lib/voiceLine';
import { useArslanStore } from '../stores/arslanStore';

export type ConversationPhase = 'off' | 'arming' | 'listening' | 'muted';

export interface ConversationOptions {
  enabled: boolean;
  locale: string;
  silenceMs: number;
  onFinal: (text: string) => void;
  onError: (message: string) => void;
}

function tauri(): any { return (window as any).__TAURI__; }

export function useConversationMode(opts: ConversationOptions): { phase: ConversationPhase; partial: string } {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<ConversationPhase>('off');
  const [partial, setPartial] = useState('');
  const speaking = useArslanStore((s) => s.speaking);
  // Callbacks in refs so a re-render never restarts the helper.
  const cb = useRef({ onFinal: opts.onFinal, onError: opts.onError, t });
  cb.current = { onFinal: opts.onFinal, onError: opts.onError, t };

  useEffect(() => {
    const tr = tauri();
    if (!opts.enabled || !tr?.core?.invoke || !tr?.event?.listen) {
      setPhase('off');
      return;
    }
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    (async () => {
      const un = await tr.event.listen('voice://conv', (e: { payload: string }) => {
        const line = parseLine(e.payload);
        if (!line) return;
        if (line.t === 'ready') { setPhase((p) => (p === 'muted' ? p : 'listening')); setPartial(''); }
        else if (line.t === 'partial') setPartial(line.text);
        else if (line.t === 'final') {
          setPartial('');
          if (line.text.trim()) cb.current.onFinal(line.text.trim());
        } else if (line.t === 'error') cb.current.onError(errorMessage(line.code, line.msg, cb.current.t));
        else if (line.t === 'ended') setPhase('off');
      });
      if (cancelled) { un(); return; }
      unlisten = un;
      setPhase('arming');
      try {
        await tr.core.invoke('voice_conversation_start', { locale: opts.locale, silenceMs: opts.silenceMs });
      } catch (e) {
        cb.current.onError(String(e));
        setPhase('off');
      }
    })();
    return () => {
      cancelled = true;
      unlisten?.();
      setPhase('off');
      setPartial('');
      tr.core.invoke('voice_conversation_stop').catch(() => { /* the helper dies with its stdin anyway */ });
    };
  }, [opts.enabled, opts.locale, opts.silenceMs]);

  // The microphone gate. `speaking` is the speaker's own bookkeeping, so the
  // mute lasts exactly as long as the reply is audible, not as long as the
  // stream takes to arrive.
  useEffect(() => {
    if (phase === 'off' || phase === 'arming') return;
    const tr = tauri();
    if (!tr?.core?.invoke) return;
    if (speaking) {
      setPhase('muted');
      tr.core.invoke('voice_mute').catch(() => {});
    } else {
      setPhase('listening');
      tr.core.invoke('voice_unmute').catch(() => {});
    }
  }, [speaking, phase === 'off' || phase === 'arming']);

  return { phase, partial };
}
