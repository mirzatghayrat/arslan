import React from 'react';
import {
  AbsoluteFill,
  Easing,
  Freeze,
  Img,
  interpolate,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {FILM_FRAMES, SHOTS} from '../ArslanFilm';
import {Cta} from '../components/Cta';
import {Mockup, MOCKUPS, SCREEN} from '../components/Mockup';
import {shotAt, viewAt} from '../lib/shots';

/**
 * FILM 10 — "GLASS". The 60-second cinematic cut, with the real client behind
 * the glass instead of a drawing of it.
 *
 * Everything the camera does here belongs to `ArslanFilm`: the same `SHOTS`
 * array is imported, not copied, so the pull-back out of the character, the
 * drift across the three-quarter plate and the top-down rotation for the graph
 * are identical. What changes is only what is on the screen.
 *
 * THE RULE THIS FILM EXISTS TO KEEP. Every pixel of product lives inside the
 * MacBook's glass. Nothing is set down beside the machine, there is never a
 * second object competing with it, and the focus never leaves the app. That was
 * the brief from the first round of mock-ups and it is easy to lose the moment
 * you have nice-looking assets: a screenshot and a character plate side by side
 * in the same frame is two things arranged, not one thing shown.
 *
 * WHAT GOES BEHIND THE GLASS:
 *   - the opening, the 2560x1440 character clip, full bleed, exactly as before
 *     but at twice the resolution
 *   - then real 2560x1680 screenshots from `public/rec/`, one per shot, each
 *     drifting slightly inside the glass so the screen is never a still
 *   - a soft cursor that travels and clicks, which is the only invented element
 *     and is a pointer rather than an interface
 *
 * No captions anywhere. The film carries its argument in what it shows.
 */

export const GLASS_FRAMES = FILM_FRAMES;

const EASE = Easing.bezier(0.33, 0, 0.16, 1);
const ramp = (f: number, s: number, l: number, e = EASE) =>
  interpolate(f, [s, s + l], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: e,
  });

/* ================================================================== */

const PLATES: Record<string, {w: number; h: number}> = {
  'rec/ledger.jpg': {w: 2560, h: 1680},
};
const plateSize = (src: string) => PLATES[src] ?? {w: 1920, h: 1260};

/**
 * A screenshot filling the glass.
 *
 * Fitted by WIDTH, not height. The plates are 1.524:1 and the glass is 1.447:1,
 * so a height fit overhangs by about 2.6% each side — and with any push on top
 * of that the first thing off the right edge is the SYNTHESIZE SPAWN button,
 * which is the one control on the ledger worth seeing. Fitted by width the
 * whole window is in frame and the 28px of screen background above and below is
 * the same near-black as the app, so it reads as bezel and disappears.
 *
 * `drift` is what stops the screen being a photograph. It is small on purpose —
 * a few per cent over a whole shot — because the camera is already moving, and
 * two moves fighting each other is what made the earliest cut read as slides.
 */
const Plate: React.FC<{src: string; f: number; from?: number; to?: number; ox?: string}> = ({
  src,
  f,
  from = 1.0,
  to = 1.04,
  ox = '50% 50%',
}) => {
  const p = plateSize(src);
  const w = SCREEN.w;
  const h = (p.h / p.w) * w;
  const k = interpolate(f, [0, 240], [from, to], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.4, 1),
  });
  return (
    <AbsoluteFill style={{overflow: 'hidden', background: '#0B0F14'}}>
      <Img
        src={staticFile(src)}
        style={{
          position: 'absolute',
          left: 0,
          top: (SCREEN.h - h) / 2,
          width: w,
          height: h,
          transform: `scale(${k})`,
          transformOrigin: ox,
        }}
      />
    </AbsoluteFill>
  );
};

/**
 * The pointer. The one thing on the glass that is not a screenshot, and it is
 * deliberately a cursor and a soft ring rather than anything that could be
 * mistaken for a control the product does not have.
 */
const Cursor: React.FC<{f: number; path: [number, number][]; clicks: number[]}> = ({
  f,
  path,
  clicks,
}) => {
  if (path.length < 2) return null;
  const legs = path.length - 1;
  const per = 78;
  const g = Math.min(legs - 0.0001, Math.max(0, (f - 40) / per));
  const i = Math.floor(g);
  const t = EASE(g - i);
  const x = path[i][0] + (path[i + 1][0] - path[i][0]) * t;
  const y = path[i][1] + (path[i + 1][1] - path[i][1]) * t;

  let pulse = 0;
  for (const c of clicks) if (f >= c && f < c + 26) pulse = Math.max(pulse, 1 - (f - c) / 26);

  const o = ramp(f, 24, 26) * (1 - ramp(f, 340, 40));
  if (o <= 0.01) return null;

  return (
    <div style={{position: 'absolute', left: x, top: y, opacity: o}}>
      {pulse > 0 ? (
        <div
          style={{
            position: 'absolute',
            left: -46 - pulse * 24,
            top: -46 - pulse * 24,
            width: 92 + pulse * 48,
            height: 92 + pulse * 48,
            borderRadius: '50%',
            border: `3px solid rgba(255,138,61,${pulse * 0.85})`,
            boxShadow: `0 0 ${34 * pulse}px rgba(255,138,61,${pulse * 0.5})`,
          }}
        />
      ) : null}
      <svg width={40} height={54} viewBox="0 0 20 27" style={{overflow: 'visible'}}>
        <path
          d="M1 1 L1 20 L6 15.5 L9.5 24 L13 22.5 L9.6 14.4 L16 14 Z"
          fill="#fff"
          stroke="rgba(0,0,0,0.45)"
          strokeWidth={1}
          style={{filter: 'drop-shadow(0 3px 8px rgba(0,0,0,0.55))'}}
        />
      </svg>
    </div>
  );
};

/* ================================================================== */

/** 3.35s at 24fps → 100 frames on this 30fps timeline. */
const CAT = {src: 'character/arslan-cat-2k.mp4', frames: 100};

const HANDOFF = 322; // frame the opening clip gives way to the client
const HANDOFF_LEN = 52;

/**
 * The opening: the character full bleed, handing off to the first real screen.
 * The clip is 2K now, so at full glass width it is running under its native
 * size instead of over it for the first time in this film's life.
 */
const Opening: React.FC<{f: number}> = ({f}) => {
  const out = ramp(f, HANDOFF, HANDOFF_LEN);
  return (
    <AbsoluteFill style={{background: '#0B0F14', overflow: 'hidden'}}>
      {out > 0 ? (
        <AbsoluteFill
          style={{
            opacity: Math.min(1, out * 2),
            filter: `blur(${(1 - out) * 16}px) brightness(${1 + (1 - out) * 1.1})`,
          }}
        >
          <Plate src="rec/home.jpg" f={f - HANDOFF} from={1.06} to={1.0} />
        </AbsoluteFill>
      ) : null}
      {out < 1 ? (
        <AbsoluteFill
          style={{
            opacity: 1 - out,
            filter: `blur(${out * 18}px) brightness(${1 + out * 1.3})`,
          }}
        >
          <Freeze frame={Math.min(f, CAT.frames - 1)}>
            <OffthreadVideo
              src={staticFile(CAT.src)}
              muted
              style={{width: SCREEN.w, height: SCREEN.h, objectFit: 'cover'}}
            />
          </Freeze>
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};

/**
 * One screen per shot, and the shot ids come from `ArslanFilm.SHOTS`.
 *
 * The pairing is not arbitrary — it follows the note already in that file about
 * which layout survives which plate. `spawns` and `safety` sit on the flat
 * front mock-up and get the two pages that are tables; `promotion` sits on the
 * three-quarter and gets the dialog, whose split runs with the foreshortening;
 * `brain` sits on the rotated top-down plate and gets the graph, which has no
 * rows to misread.
 */
const VIEWS: Record<string, {src: string; from?: number; to?: number; ox?: string}> = {
  thread: {src: 'rec/chat.jpg', from: 1.0, to: 1.05, ox: '62% 42%'},
  spawns: {src: 'rec/ledger.jpg', from: 1.04, to: 1.0},
  promotion: {src: 'rec/create.jpg', from: 1.0, to: 1.045, ox: '46% 56%'},
  safety: {src: 'rec/auto.jpg', from: 1.04, to: 1.0, ox: '66% 46%'},
  brain: {src: 'rec/brain.jpg', from: 1.0, to: 1.05},
  close: {src: 'rec/brain.jpg', from: 1.0, to: 1.05},
};

/** Where the pointer goes on each page, in 1600x1106 screen space. */
const PATHS: Record<string, {path: [number, number][]; clicks: number[]}> = {
  thread: {path: [[980, 830], [1180, 700], [1240, 250]], clicks: [118, 196]},
  spawns: {path: [[420, 300], [700, 520], [1120, 540]], clicks: [118, 196]},
  promotion: {path: [[520, 360], [820, 640], [1300, 900]], clicks: [118, 196, 274]},
  safety: {path: [[520, 560], [1180, 400], [1180, 690]], clicks: [118, 196]},
  brain: {path: [[900, 520], [1080, 620]], clicks: [118]},
};

const Screen: React.FC<{id: string; f: number; since: number}> = ({id, f, since}) => {
  if (id === 'open' || id === 'reveal' || id === 'settle') return <Opening f={f} />;
  const v = VIEWS[id] ?? VIEWS.brain;
  const p = PATHS[id];
  const t = f - since;
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      <Plate src={v.src} f={t} from={v.from} to={v.to} ox={v.ox} />
      {p ? <Cursor f={t} path={p.path} clicks={p.clicks} /> : null}
    </AbsoluteFill>
  );
};

/**
 * Film-relative, so a view carried across a cut does not restart. `thread` and
 * `spawns` are one continuous take of the client in two shots; resetting the
 * drift at the seam would show.
 */
const SINCE: Record<string, number> = {
  thread: 0,
  spawns: 588,
  promotion: 736,
  safety: 1032,
  brain: 1240,
  close: 1240,
};

export const Glass: React.FC = () => {
  const frame = useCurrentFrame();
  const {shot, t} = shotAt(SHOTS, frame);
  const view = viewAt(shot, t);

  return (
    <AbsoluteFill style={{background: MOCKUPS[shot.mockup].void, overflow: 'hidden'}}>
      <Mockup mockup={shot.mockup} view={view}>
        <Screen id={shot.id} f={frame} since={SINCE[shot.id] ?? 0} />
      </Mockup>
      <Cta start={GLASS_FRAMES - 142} />
    </AbsoluteFill>
  );
};
