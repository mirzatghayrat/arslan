import { useCallback, useRef, useSyncExternalStore } from 'react';
import { useArslanStore } from '../stores/arslanStore';

/**
 * FMT1 (0.1.64): the reply being streamed, at most once per animation frame. Each chunk is its own WebSocket message, and each
 * message re-rendered the chat before this, so a reattach replaying a turn's frames took 20 s to drain (measured in the PR). The
 * store stays exact: this only decides when the window looks.
 *
 * A reply that shrinks shows at once: a new one must not start by showing the last one, and one a guard sent back must not
 * linger. A hidden window gets no frames and needs none: the finished reply comes from the store's items, not from here.
 */
export function useStreamingText(): string {
  const shown = useRef(useArslanStore.getState().streamingText);
  const subscribe = useCallback((notify: () => void) => {
    let due = 0;
    const show = () => {
      due = 0;
      shown.current = useArslanStore.getState().streamingText;
      notify();
    };
    const unsubscribe = useArslanStore.subscribe(({ streamingText: text }) => {
      if (text.length < shown.current.length) {
        cancelAnimationFrame(due);
        show();
      } else if (text !== shown.current) {
        due ||= requestAnimationFrame(show);
      }
    });
    return () => {
      unsubscribe();
      cancelAnimationFrame(due);
    };
  }, []);
  return useSyncExternalStore(subscribe, () => shown.current);
}
