import {Easing, interpolate, type EasingFunction} from 'remotion';
import type {MockupName, View} from '../components/Mockup';

/**
 * A film as a list of shots.
 *
 * Both cuts are the same seven or so beats at different lengths, so neither
 * gets to hand-position a camera per frame. A shot names its mock-up, where the
 * camera starts, where it ends, and how it gets there; the film is the list.
 * That makes re-timing a cut an edit to two numbers instead of a rewrite, and
 * it makes the difference between the 30 and the 60 legible as what it is — the
 * same story told at two speeds with different shot lengths.
 */

export type Ease = 'settle' | 'drift' | 'ease';

const CURVES: Record<Ease, EasingFunction> = {
  /** Decelerates to a stop. For a move that has arrived somewhere. */
  settle: Easing.bezier(0.22, 1, 0.36, 1),
  /** Constant rate. The cut lands mid-move and the shot never freezes. */
  drift: (t) => t,
  /** Eased both ends. For a move that is the whole point of the shot. */
  ease: Easing.bezier(0.4, 0, 0.2, 1),
};

export type Shot = {
  id: string;
  mockup: MockupName;
  /** First frame of the shot, in film time. */
  start: number;
  /** Frames the shot is on screen. */
  duration: number;
  from: View;
  to: View;
  ease?: Ease;
  /**
   * Extra frames the move is spread over beyond the shot's own length.
   *
   * The single most useful control here. A camera that reaches its mark and
   * stops dead a beat before the cut reads as a slideshow of moving pictures;
   * spreading the same move over a longer span and cutting away part-way
   * through means every shot is still travelling when it ends. Nothing in the
   * film ever comes to rest except the last frame.
   */
  tail?: number;
};

/** Which shot is on screen, and how far into it we are. */
export const shotAt = (shots: Shot[], frame: number) => {
  let active = shots[0];
  for (const s of shots) {
    if (frame >= s.start) active = s;
  }
  return {shot: active, t: frame - active.start};
};

/** The camera, for a frame within a shot. */
export const viewAt = (shot: Shot, t: number): View => {
  const span = shot.duration + (shot.tail ?? 0);
  const p = interpolate(t, [0, span], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: CURVES[shot.ease ?? 'drift'],
  });
  return {
    cx: shot.from.cx + (shot.to.cx - shot.from.cx) * p,
    cy: shot.from.cy + (shot.to.cy - shot.from.cy) * p,
    w: shot.from.w + (shot.to.w - shot.from.w) * p,
  };
};

/** Lay shots end to end, so only durations have to be authored. */
export const sequence = (
  specs: (Omit<Shot, 'start'> & {start?: number})[],
): Shot[] => {
  let at = 0;
  return specs.map((s) => {
    const shot = {...s, start: s.start ?? at} as Shot;
    at = shot.start + shot.duration;
    return shot;
  });
};

export const filmLength = (shots: Shot[]) =>
  Math.max(...shots.map((s) => s.start + s.duration));

/** Named camera positions, so the two films can share framings. */
export type Framing = (out: number, dx?: number, dy?: number) => View;

export const framings = (glass: {cx: number; cy: number; w: number}): Framing =>
  (out, dx = 0, dy = 0) => ({cx: glass.cx + dx, cy: glass.cy + dy, w: glass.w * out});
