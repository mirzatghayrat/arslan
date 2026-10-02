/**
 * The mascot's mouth constellation (three lines, four dots) as data and pure
 * math, ported from the approved mock (v3). The head itself never moves except
 * for breathing and blinking (CSS); every state is a shape this constellation
 * morphs into. A JS tween, because WKWebView has no CSS `d` transitions.
 *
 * C = top dot, L/R = side dots, B = bottom dot, each [x, y, r] in the head's
 * viewBox (250 190 750 840). S = the C→B line as two cubic segments
 * (14 numbers), so it can bend into "?" or the cat smile. w = line width.
 */
import type { Mood } from './islandMachine';

export type Dot = [number, number, number];
export interface Glyph { C: Dot; L: Dot; R: Dot; B: Dot; S: number[]; w: number }
export type GlyphName = 'y' | 'bang' | 'ask' | 'smile' | 'orbit' | 'flat' | 'small';

const line = (x0: number, y0: number, x1: number, y1: number) => {
  const o = [x0, y0];
  for (let i = 1; i <= 6; i++) o.push(x0 + ((x1 - x0) * i) / 6, y0 + ((y1 - y0) * i) / 6);
  return o;
};
const at = (x: number, y: number) => line(x, y, x, y);

export const GLYPH: Record<GlyphName, Glyph> = {
  y: { C: [626, 696, 29], L: [495, 813, 25], R: [757, 813, 25], B: [626, 893, 30], S: line(626, 696, 626, 893), w: 10 },
  bang: { C: [626, 640, 0], L: [626, 640, 0], R: [626, 640, 0], B: [626, 884, 27], S: line(626, 640, 626, 800), w: 36 },
  ask: {
    C: [566, 704, 0], L: [566, 704, 0], R: [566, 704, 0], B: [626, 886, 26],
    S: [566, 704, 566, 634, 686, 626, 686, 700, 686, 752, 626, 750, 626, 812], w: 32,
  },
  smile: {
    C: [626, 736, 27], L: [626, 736, 0], R: [626, 736, 0], B: [626, 806, 0],
    S: [528, 800, 528, 862, 626, 862, 626, 806, 626, 862, 724, 862, 724, 800], w: 26,
  },
  orbit: { C: [626, 790, 0], L: [546, 744, 22], R: [706, 744, 22], B: [626, 882, 22], S: at(626, 790), w: 0 },
  flat: { C: [626, 812, 0], L: [522, 812, 21], R: [730, 812, 21], B: [626, 812, 0], S: at(626, 812), w: 30 },
  small: { C: [626, 730, 18], L: [547, 800, 15], R: [705, 800, 15], B: [626, 848, 18], S: line(626, 730, 626, 848), w: 7 },
};

export const GLYPH_OF: Record<Mood, GlyphName> = {
  idle: 'y', working: 'y', searching: 'orbit', approval: 'bang', finished: 'smile', stopped: 'flat', sleeping: 'small',
};

export const MORPH_MS = 560;
export const ORBIT_RADIUS = 92;

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const easeBack = (t: number) => {
  const c = 1.35;
  return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2);
};
const mixDot = (a: Dot, b: Dot, t: number): Dot => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];

export function mix(a: Glyph, b: Glyph, t: number): Glyph {
  return {
    C: mixDot(a.C, b.C, t), L: mixDot(a.L, b.L, t), R: mixDot(a.R, b.R, t), B: mixDot(a.B, b.B, t),
    S: a.S.map((v, i) => lerp(v, b.S[i], t)), w: lerp(a.w, b.w, t),
  };
}

export interface Frame { g: Glyph; sparks: Dot[]; ring: number }

/**
 * One frame: the tweened glyph (t = 0…1 through the morph) plus the state's
 * own motion at time `sec` — signals running down the lines while working,
 * the three dots chasing each other round the centre while searching, the
 * cat smile curling, the "!" dot pulsing, a slow dim pulse while away.
 */
export function frameAt(mood: Mood, from: Glyph, to: Glyph, t: number, sec: number): Frame {
  const g = mix(from, to, easeBack(Math.min(1, Math.max(0, t))));
  const d: Glyph = { ...g, C: [...g.C] as Dot, L: [...g.L] as Dot, R: [...g.R] as Dot, B: [...g.B] as Dot, S: [...g.S] };
  const sparks: Dot[] = [];
  let ring = 0;
  if (mood === 'searching') {
    const ease = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
    const grow = Math.min(1, t * 1.1);
    ring = ORBIT_RADIUS * grow;
    (['B', 'L', 'R'] as const).forEach((k, i) => {
      const ti = sec * 0.72 - i * 0.075;
      const turn = Math.floor(ti) + ease(ti - Math.floor(ti));
      const a = Math.PI / 2 + i * ((2 * Math.PI) / 3) + turn * 2 * Math.PI * grow;
      d[k] = [lerp(d[k][0], d.C[0] + ORBIT_RADIUS * Math.cos(a), grow), lerp(d[k][1], d.C[1] + ORBIT_RADIUS * Math.sin(a), grow), d[k][2]];
    });
  } else if (mood === 'working') {
    (['L', 'R', 'B'] as const).forEach((k, i) => {
      const ph = (sec / 1.05 + i * 0.33) % 1;
      const e = ph * ph * (3 - 2 * ph);
      sparks.push([lerp(d.C[0], d[k][0], e), lerp(d.C[1], d[k][1], e), 15 * Math.sin(Math.PI * ph)]);
      const arrive = Math.max(0, 1 - Math.abs(ph - 0.97) * 14);
      d[k][2] *= 1 + 0.45 * arrive;
    });
  } else if (mood === 'finished' && t >= 1) {
    const k = 9 * Math.sin(sec * 3.4);
    [3, 5, 9, 11].forEach((i) => { d.S[i] += k; });
  } else if (mood === 'approval' && t >= 1) {
    d.B[2] *= 1 + 0.14 * (0.5 + 0.5 * Math.sin(sec * 6.6));
  } else if (mood === 'sleeping') {
    const k = 0.94 + 0.06 * Math.sin(sec * 1.2);
    d.L[2] *= k; d.R[2] *= k; d.B[2] *= k; d.C[2] *= k;
  }
  return { g: d, sparks, ring };
}

export function stemPath(S: number[]): string {
  const f = S.map((v) => v.toFixed(1));
  return `M${f[0]} ${f[1]}C${f[2]} ${f[3]} ${f[4]} ${f[5]} ${f[6]} ${f[7]}C${f[8]} ${f[9]} ${f[10]} ${f[11]} ${f[12]} ${f[13]}`;
}
