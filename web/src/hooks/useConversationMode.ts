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
  /** The helper process is gone — the shell's `ended` line. The caller owns
   *  the toggle, so only it can put the button back; the hook going `off` by
   *  itself just leaves a lit control over a dead session. */
  onEnded?: () => void;
}

function tauri(): any { return (window as any).__TAURI__; }

export function useConversationMode(opts: ConversationOptions): { phase: ConversationPhase; partial: string } {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<ConversationPhase>('off');
  const [partial, setPartial] = useState('');
  const speaking = useArslanStore((s) => s.speaking);
  // Callbacks in refs so a re-render never restarts the helper.
  const cb = useRef({ onFinal: opts.onFinal, onError: opts.onError, onEnded: opts.onEnded, t });
  cb.current = { onFinal: opts.onFinal, onError: opts.onError, onEnded: opts.onEnded, t };
  // What `speaking` was the last time the gate acted. The gate's effect also
  // re-runs when the phase leaves `arming`, and without this it treated that
  // as "not speaking" all over again and wrote an unmute down the pipe to a
  // helper that had never been muted.
  const wasSpeaking = useRef(false);

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
        else if (line.t === 'ended') { setPhase('off'); cb.current.onEnded?.(); }
      });
      if (cancelled) { un(); return; }
      unlisten = un;
      setPhase('arming');
      try {
        await tr.core.invoke('voice_conversation_start', { locale: opts.locale, silenceMs: opts.silenceMs });
        // The cleanup may have run while that invoke was in flight. Its own
        // `voice_conversation_stop` reached a shell that had not spawned
        // anything yet, so the helper that exists now belongs to nobody and
        // would hold the microphone until the app quits. Stop it again, now
        // that there is something to stop.
        if (cancelled) {
          tr.core.invoke('voice_conversation_stop').catch(() => {});
          return;
        }
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
      // The next helper starts unmuted, whatever this one was doing.
      wasSpeaking.current = false;
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
    // Only a real change of the speaker's state is a command worth sending.
    // This effect also fires when the phase leaves `arming`, and that is not
    // news about the microphone.
    if (speaking === wasSpeaking.current) return;
    wasSpeaking.current = speaking;
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
