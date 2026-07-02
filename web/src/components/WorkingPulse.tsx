import { useEffect, useRef, useState } from 'react';

/**
 * WorkingPulse — a decrypt/scramble text indicator for every "something is happening"
 * moment (no dead air, ever). Cycles through phase phrases; each resolves left-to-right
 * out of random glyphs, holds briefly, then the next phrase scrambles in.
 *
 * Written in-house (~50 lines): react-bits' DecryptedText is MIT+Commons-Clause, which
 * we do not mix into this MIT codebase. No dependencies, respects reduced motion.
 */
const GLYPHS = 'ABCDEFGHJKMNPQRSTUVWXYZ023456789#$%&*+=<>/\\|~';

function scrambleFrame(target: string, progress: number): string {
  // progress 0→1: chars before the frontier are resolved, the rest are random glyphs.
  const frontier = Math.floor(target.length * progress);
  let out = '';
  for (let i = 0; i < target.length; i++) {
    const ch = target[i];
    if (i < frontier || ch === ' ') out += ch;
    else out += GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
  }
  return out;
}

export default function WorkingPulse({
  phrases,
  className = '',
  periodMs = 3800,
}: {
  phrases: string[];
  className?: string;
  periodMs?: number;
}) {
  const [text, setText] = useState('');
  const idx = useRef(0);
  const reduced = typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;

  useEffect(() => {
    if (!phrases.length) return;
    if (reduced) {
      // No scramble for reduced-motion users — plain rotating text.
      setText(phrases[0]);
      const rot = setInterval(() => {
        idx.current = (idx.current + 1) % phrases.length;
        setText(phrases[idx.current]);
      }, periodMs);
      return () => clearInterval(rot);
    }
    const resolveMs = Math.min(1500, periodMs * 0.4);
    let start = performance.now();
    const tick = setInterval(() => {
      const elapsed = (performance.now() - start) % periodMs;
      if (elapsed < resolveMs) {
        setText(scrambleFrame(phrases[idx.current % phrases.length], elapsed / resolveMs));
      } else {
        setText(phrases[idx.current % phrases.length]);
        if (elapsed + 80 >= periodMs) idx.current += 1;
      }
    }, 80);
    return () => clearInterval(tick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phrases.join('|'), periodMs, reduced]);

  return (
    <span className={`font-mono tabular-nums select-none ${className}`} aria-live="polite">
      {text || phrases[0] || ''}
    </span>
  );
}
