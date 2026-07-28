import {Easing, interpolate, spring} from 'remotion';
import {VIDEO} from '../theme';

/** The one easing curve the whole film uses for non-spring moves. */
export const ease = Easing.bezier(0.22, 1, 0.36, 1);
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);

const CLAMP = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

/** 0 → 1 over `length` frames starting at `start`, on the house curve. */
export const ramp = (frame: number, start: number, length: number) =>
  interpolate(frame, [start, start + length], [0, 1], {...CLAMP, easing: ease});

/** Fade in, hold, fade out — the standard beat envelope. */
export const beat = (
  frame: number,
  start: number,
  hold: number,
  fade = 12,
): number =>
  interpolate(
    frame,
    [start, start + fade, start + fade + hold, start + fade + hold + fade],
    [0, 1, 1, 0],
    {...CLAMP, easing: easeInOut},
  );

/** Snappy entrance spring, tuned once so every element lands the same way. */
export const pop = (frame: number, delay = 0, damping = 200) =>
  spring({
    frame: frame - delay,
    fps: VIDEO.fps,
    config: {damping, mass: 0.6, stiffness: 120},
    durationInFrames: 30,
  });

/** Values that step rather than glide — counters, scores, percentages. */
export const countTo = (
  frame: number,
  start: number,
  length: number,
  to: number,
  from = 0,
) => interpolate(frame, [start, start + length], [from, to], {...CLAMP, easing: ease});

/**
 * Reveals `text` one character at a time. `cps` is characters per second, so
 * timing stays readable when a line is rewritten.
 */
export const typed = (
  frame: number,
  start: number,
  text: string,
  cps = 42,
): string => {
  const chars = Math.floor(((frame - start) / VIDEO.fps) * cps);
  if (chars <= 0) return '';
  return text.slice(0, chars);
};

export const typedDone = (frame: number, start: number, text: string, cps = 42) =>
  frame - start >= (text.length / cps) * VIDEO.fps;

/** Stroke-dash draw-on for any SVG path of known length. */
export const drawPath = (progress: number, length: number) => ({
  strokeDasharray: length,
  strokeDashoffset: length * (1 - progress),
});

/** Deterministic pseudo-random in [0,1) — no Math.random, renders must repeat. */
export const rand = (seed: number) => {
  const x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
};
