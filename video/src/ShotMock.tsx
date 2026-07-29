import React from 'react';
import {AbsoluteFill, Freeze, OffthreadVideo, staticFile, useCurrentFrame} from 'remotion';
import {ScreenBrain, ScreenPromotion, ScreenThread} from './components/AppScreen';
import {
  glassBox,
  insideGlass,
  Mockup,
  MOCKUPS,
  SCREEN,
  type MockupName,
  type View,
} from './components/Mockup';
import {CHARACTER_OPEN} from './lightTheme';
import {font} from './theme';

/**
 * One frame per shot, so a framing can be rendered with `remotion still` and
 * looked at before any of it is committed to a 900-frame render.
 *
 * Every shot is a real photograph of a machine with the app composited onto its
 * glass. The three rules the earlier passes broke are structural here rather
 * than remembered: all product content is inside the screen (there is nowhere
 * else to put it), only one machine is ever in frame (a mock-up holds exactly
 * one), and the environment is the warm set the pictures were made on.
 */

type Content = 'cat' | 'thread' | 'promotion' | 'brain';

type Shot = {
  id: string;
  note: string;
  mockup: MockupName;
  view: View;
  content: Content;
  /** Frame fed to the screen's own animation. */
  at: number;
  cta?: boolean;
};

/**
 * Frame the glass of `m`, then pull back by `out`. 1 = the glass spans the
 * frame's WIDTH.
 *
 * Worth being careful with on the angled mock-ups: their glass is taller
 * relative to its width than a 16:9 frame, so `out = 1` still crops the top and
 * bottom off the display. Anything meant to show a whole screen wants roughly
 * 1.4 and up, and below about 1.3 the machine leaves frame entirely and the
 * shot stops being a shot — it reads as a screen recording.
 */
const pull = (m: MockupName, out: number, dx = 0, dy = 0): View => {
  const g = insideGlass(m);
  return {cx: g.cx + dx, cy: g.cy + dy, w: g.w * out};
};

const SHOTS: Shot[] = [
  {
    id: 'A',
    note: 'Open. Character full bleed, inside the glass, no bezel yet. Same shot as B and C.',
    mockup: 'front',
    view: pull('front', 0.86),
    content: 'cat',
    at: 10,
  },
  {
    id: 'B',
    note: 'The SAME shot, mid pull-back. Clip still running, bezel has just arrived.',
    mockup: 'front',
    view: pull('front', 1.32, 0, 0.012),
    content: 'cat',
    at: 74,
  },
  {
    id: 'C',
    note: 'Same move, settled. It was a machine on a desk all along; clip still running.',
    mockup: 'front',
    view: pull('front', 2.34, 0, 0.055),
    content: 'cat',
    at: 140,
  },
  {
    id: 'D',
    note: 'Cut. Three-quarter, app has the screen. Legible, glass foreshortened.',
    mockup: 'threequarter',
    view: pull('threequarter', 1.78, 0.012, 0.03),
    content: 'thread',
    at: 150,
  },
  {
    id: 'E',
    note: 'Cut to the profile for the promotion gate. Pushed in so the exam reads.',
    mockup: 'side',
    view: pull('side', 1.86, 0.055, 0.035),
    content: 'promotion',
    at: 104,
  },
  {
    id: 'F',
    note: 'Second brain, top-down and pushed in. Same shot as G — the film does not cut again.',
    mockup: 'top',
    view: pull('top', 1.78, 0.004, 0.012),
    content: 'brain',
    at: 150,
  },
  {
    id: 'G',
    note: 'The SAME shot, pulled back and drifting. Machine goes right, CTA arrives in the amber it leaves behind.',
    mockup: 'top',
    view: {cx: 0.3, cy: 0.45, w: 1.16},
    content: 'brain',
    at: 190,
    cta: true,
  },
];

export const SHOT_COUNT = SHOTS.length;

const Screen: React.FC<{kind: Content; at: number}> = ({kind, at}) => {
  if (kind === 'cat') {
    return (
      <AbsoluteFill>
        <Freeze frame={Math.min(at, CHARACTER_OPEN.frames - 1)}>
          <OffthreadVideo
            src={staticFile(CHARACTER_OPEN.src)}
            muted
            style={{width: SCREEN.w, height: SCREEN.h, objectFit: 'cover'}}
          />
        </Freeze>
      </AbsoluteFill>
    );
  }
  if (kind === 'thread') return <ScreenThread frame={at} />;
  if (kind === 'promotion') return <ScreenPromotion frame={at} />;
  return <ScreenBrain frame={at} />;
};

/**
 * The close.
 *
 * Type in world space is the one thing that must never touch the machine — a
 * caption laid across the hardware turns an app demo into a laptop advert. The
 * top-down mock-up earns this shot because the set around the machine is empty
 * amber, so the words have somewhere of their own to sit.
 */
export const Cta: React.FC<{o?: number}> = ({o = 1}) => (
  <div
    style={{
      position: 'absolute',
      left: 128,
      top: 296,
      width: 620,
      fontFamily: font.sans,
      opacity: o,
    }}
  >
    <div
      style={{
        fontSize: 92,
        fontWeight: 650,
        letterSpacing: '-0.04em',
        color: '#FFF6EA',
        lineHeight: 1.02,
        textShadow: '0 10px 40px rgba(60,26,0,0.4)',
      }}
    >
      Arslan
    </div>
    <div
      style={{
        marginTop: 20,
        fontSize: 26,
        color: 'rgba(255,238,219,0.86)',
        lineHeight: 1.45,
        maxWidth: 510,
      }}
    >
      One host agent. Spawns you raised. Nothing ships until you press Promote.
    </div>
    <div
      style={{
        marginTop: 44,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 15,
        background: '#FFF6EA',
        color: '#231204',
        borderRadius: 999,
        padding: '20px 38px',
        fontSize: 25,
        fontWeight: 600,
        boxShadow: '0 20px 54px rgba(48,20,0,0.45)',
      }}
    >
      <span style={{fontSize: 23}}>↓</span>
      Download for macOS
    </div>
    <div
      style={{
        marginTop: 18,
        fontFamily: font.mono,
        fontSize: 15,
        color: 'rgba(255,235,213,0.66)',
        letterSpacing: '0.06em',
      }}
    >
      macOS 11+ · Apple Silicon · signed &amp; notarized
    </div>
  </div>
);

export const ShotMock: React.FC = () => {
  const frame = useCurrentFrame();
  const shot = SHOTS[Math.min(frame, SHOTS.length - 1)];

  return (
    <AbsoluteFill style={{background: MOCKUPS[shot.mockup].void, overflow: 'hidden'}}>
      <Mockup mockup={shot.mockup} view={shot.view}>
        <Screen kind={shot.content} at={shot.at} />
      </Mockup>
      {shot.cta ? <Cta /> : null}
    </AbsoluteFill>
  );
};

export {glassBox};
