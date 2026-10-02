import { useEffect, useId, useRef } from 'react';
import type { Mood } from './islandMachine';
import { GLYPH, GLYPH_OF, MORPH_MS, frameAt, stemPath, type Dot, type Glyph } from './mascotEngine';

const STILL = new Set<Mood>(['idle', 'stopped']);

/**
 * Arslan's black-and-white head (the brand mark's own shapes). It breathes and
 * blinks; the mouth constellation carries the state. `paused` stops the frame
 * loop while the island is hidden behind the notch.
 */
export default function IslandMascot({ mood, size, paused = false, small = false }:
  { mood: Mood; size: number; paused?: boolean; small?: boolean }) {
  const gid = useId().replace(/:/g, '');
  const refs = useRef<Record<string, SVGElement | null>>({});
  const anim = useRef<{ cur: Glyph; from: Glyph; to: Glyph; t0: number; mood: Mood }>({
    cur: GLYPH.y, from: GLYPH.y, to: GLYPH[GLYPH_OF[mood]], t0: performance.now(), mood,
  });

  useEffect(() => {
    const a = anim.current;
    if (a.mood === mood) return;
    a.from = a.cur;
    a.to = GLYPH[GLYPH_OF[mood]];
    a.t0 = performance.now();
    a.mood = mood;
  }, [mood]);

  useEffect(() => {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    let raf = 0;
    const setLine = (el: SVGElement | null, p: Dot, q: Dot, w: number) => {
      if (!el) return;
      el.setAttribute('x1', String(p[0])); el.setAttribute('y1', String(p[1]));
      el.setAttribute('x2', String(q[0])); el.setAttribute('y2', String(q[1]));
      el.setAttribute('stroke-width', String(w));
    };
    const setDot = (el: SVGElement | null, c: Dot) => {
      if (!el) return;
      el.setAttribute('cx', String(c[0])); el.setAttribute('cy', String(c[1]));
      el.setAttribute('r', String(Math.max(0, c[2])));
    };
    const draw = (now: number) => {
      const a = anim.current;
      const t = reduce ? 1 : Math.min(1, (now - a.t0) / MORPH_MS);
      const { g, sparks, ring } = frameAt(a.mood, a.from, a.to, t, reduce ? 0 : now / 1000);
      a.cur = t >= 1 ? a.to : g;
      const r = refs.current;
      setLine(r.cl, g.C, g.L, g.w);
      setLine(r.cr, g.C, g.R, g.w);
      r.stem?.setAttribute('d', stemPath(g.S));
      r.stem?.setAttribute('stroke-width', String(g.w));
      setDot(r.nc, g.C); setDot(r.nl, g.L); setDot(r.nr, g.R); setDot(r.nb, g.B);
      [r.s0, r.s1, r.s2].forEach((el, i) => setDot(el, sparks[i] ?? [0, 0, 0]));
      setDot(r.trk, [g.C[0], g.C[1], ring]);
    };
    // Idle and stopped have no motion of their own (breathing and blinking are
    // CSS): once the morph lands, the frame loop stops until the mood changes.
    const loop = (now: number) => {
      draw(now);
      const a = anim.current;
      if (STILL.has(a.mood) && now - a.t0 >= MORPH_MS) return;
      raf = requestAnimationFrame(loop);
    };
    if (paused || reduce) draw(performance.now() + MORPH_MS);
    else raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [paused, mood]);

  const ref = (k: string) => (el: SVGElement | null) => { refs.current[k] = el; };
  return (
    <div className={`mascot${small ? ' small' : ''}${paused ? ' paused' : ''}`} data-state={mood}
      style={{ ['--s' as string]: `${size}px` }} aria-hidden="true">
      <div className="halo" />
      <svg viewBox="250 190 750 840">
        <defs>
          <linearGradient id={`${gid}f`} x1="0.85" y1="0" x2="0.15" y2="1">
            <stop offset="0" stopColor="#ffffff" /><stop offset=".7" stopColor="#ffffff" /><stop offset="1" stopColor="#e9ebee" />
          </linearGradient>
        </defs>
        <g className="head">
          <path fill={`url(#${gid}f)`} d="M286 517L283 287C283 231 320 208 358 237L494 332Q626 280 758 332L894 237C932 208 969 231 969 287L966 517C966 562 982 603 963 651C944 694 909 731 880 777L811 890C758 974 698 1006 626 1006C554 1006 494 974 441 890L372 777C343 731 308 694 289 651C270 603 286 562 286 517Z" />
          <path className="ears" d="M310 496L307 286Q307 236 349 259L465 343Q376 404 310 496ZM942 496L945 286Q945 236 903 259L787 343Q876 404 942 496Z" />
          <g className="eyes"><path d="M386 518C478 501 558 551 552 650C449 654 387 604 386 518ZM866 518C774 501 694 551 700 650C803 654 865 604 866 518Z" /></g>
          <g className="net">
            <circle className="trk" ref={ref('trk')} />
            <line className="cl" ref={ref('cl')} /><line className="cr" ref={ref('cr')} />
            <path className="stem" ref={ref('stem')} />
            <circle ref={ref('nc')} /><circle ref={ref('nl')} /><circle ref={ref('nr')} /><circle ref={ref('nb')} />
            <circle ref={ref('s0')} /><circle ref={ref('s1')} /><circle ref={ref('s2')} />
          </g>
        </g>
      </svg>
    </div>
  );
}
