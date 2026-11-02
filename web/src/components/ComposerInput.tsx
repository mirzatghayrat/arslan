import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef } from 'react';
import type { KeyboardEvent, TextareaHTMLAttributes } from 'react';

/** SMART (the user, 2026-11-02): the chat input wraps and grows with what is typed, up to a cap, then scrolls inside.
 * The cap is MAX_LINES lines or MAX_VIEWPORT of the window's height, whichever is smaller. */
export const MAX_LINES = 12;
export const MAX_VIEWPORT = 0.4;

type Props = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'onKeyDown' | 'rows'> & {
  value: string;
  /** The lines it shows while empty (and never fewer). */
  minRows?: number;
  /** Enter, with no Shift and no composition in progress. */
  onSend: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
};

/** Both composers' text box (the first message's and the conversation's). Enter sends and Shift+Enter starts a new
 * line, as before; an Enter that confirms an input method's composition (Chinese, Japanese) only confirms it. */
export const ComposerInput = forwardRef<HTMLTextAreaElement, Props>(function ComposerInput(
  { value, minRows = 1, onSend, ...rest }, ref) {
  const box = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => box.current as HTMLTextAreaElement);
  const fit = useCallback(() => { if (box.current) fitHeight(box.current); }, []);
  useLayoutEffect(fit, [value, fit]);
  useEffect(() => {
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, [fit]);
  return (
    <textarea ref={box} rows={minRows} value={value} {...rest}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !e.shiftKey && !composing(e)) {
          e.preventDefault();
          onSend(e);
        }
      }} />
  );
});

/** Whether a keydown belongs to an input method's composition. WebKit, the app's window, gives the Enter that
 * confirms one `isComposing` false and keyCode 229. */
export function composing(e: KeyboardEvent): boolean {
  return e.nativeEvent.isComposing || e.keyCode === 229;
}

/** The box as tall as its text, up to the cap; past the cap it scrolls inside. */
export function fitHeight(el: HTMLTextAreaElement): void {
  const style = window.getComputedStyle(el);
  const line = parseFloat(style.lineHeight) || (parseFloat(style.fontSize) || 14) * 1.5;
  const pad = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
  const cap = Math.min(line * MAX_LINES + pad, window.innerHeight * MAX_VIEWPORT);
  el.style.height = 'auto';
  const content = el.scrollHeight;
  el.style.height = `${Math.min(content, cap)}px`;
  el.style.overflowY = content > cap ? 'auto' : 'hidden';
}
