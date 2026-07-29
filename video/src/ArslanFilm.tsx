import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {
  ScreenBrain,
  ScreenPromotion,
  ScreenSafety,
  ScreenSpawns,
  ScreenThread,
} from './components/AppScreen';
import {Cta} from './components/Cta';
import {glassBox, Mockup, MOCKUPS, SCREEN, type MockupName} from './components/Mockup';
import {filmLength, sequence, shotAt, viewAt} from './lib/shots';
import {CHARACTER_OPEN} from './lightTheme';

/**
 * The 60-second cut.
 *
 * Not the 30 stretched. The 30 has to win a scroll, so it is built out of
 * arrivals: every shot is already moving when it starts, the cuts come before
 * anything settles, and the app is pre-rolled so each cut lands on a screen
 * mid-thought. That reads as urgency, and urgency is what it is for.
 *
 * This one has time, so it is built out of holds. Shots begin nearer their
 * subject and travel less. Views are given long enough to finish a thought and
 * sit for a beat afterwards — the exam completes and is looked at before
 * anything is pressed, the sandbox log prints line by line. Two views the short
 * cut has no room for are here: the spawns ledger, which turns "it has
 * sub-agents" into a roster with capabilities attached, and diagnostics, where
 * the sandbox refuses a direct connection and the proxy is the only way out.
 *
 * The spine is shared and deliberately so. Both films open on the character and
 * pull back until it turns out to have been a screen, and both close by pulling
 * back off the machine into the download rather than cutting to it.
 */

/** Frame the glass of `m`, pulled back by `out`. 1 = glass spans frame width. */
const at = (m: MockupName, out: number, dx = 0, dy = 0) => {
  const b = glassBox(m);
  return {
    cx: (b.x0 + b.x1) / 2 + dx,
    cy: (b.y0 + b.y1) / 2 + dy,
    w: (b.x1 - b.x0) * out,
  };
};

export const SHOTS = sequence([
  /* ---- the opening, one continuous pull-back ------------------------- */
  {
    id: 'open',
    mockup: 'front',
    duration: 168,
    // Nearly still for the first five seconds. The 30 cannot afford this and
    // it is the best thing about the 60: a face, holding, before any claim.
    from: at('front', 0.78),
    to: at('front', 0.97, 0, 0.003),
    ease: 'ease',
    tail: 96,
  },
  {
    id: 'reveal',
    mockup: 'front',
    duration: 132,
    from: at('front', 0.97, 0, 0.003),
    to: at('front', 2.34, 0, 0.056),
    ease: 'ease',
    tail: 26,
  },
  {
    id: 'settle',
    mockup: 'front',
    duration: 90,
    // The one moment either film comes close to resting. The machine is on a
    // desk, the app is on it, and the film lets that be true for three seconds.
    from: at('front', 2.34, 0, 0.056),
    to: at('front', 2.2, 0, 0.05),
    ease: 'settle',
    tail: 40,
  },

  /* ---- the product, five views --------------------------------------- */
  {
    id: 'thread',
    mockup: 'threequarter',
    duration: 216,
    from: at('threequarter', 1.9, 0.014, 0.046),
    to: at('threequarter', 1.66, 0.006, 0.022),
    ease: 'drift',
    tail: 120,
  },
  {
    id: 'spawns',
    // Straight on, and for a reason: this view is a table. On the top-down
    // mock-up the glass is rotated 25 degrees, so a row of cells climbs the
    // frame diagonally and stops reading as a row — the one angle a table
    // cannot survive. Rotation suits the note graph, which has no rows to
    // misread; tables and panels want the flatter plates.
    mockup: 'front',
    duration: 192,
    from: at('front', 1.9, 0, 0.03),
    to: at('front', 1.7, 0, 0.018),
    ease: 'drift',
    tail: 96,
  },
  {
    id: 'promotion',
    // Two side-by-side panels, which a tilted plate handles: the split runs
    // with the foreshortening rather than across it.
    mockup: 'threequarter',
    duration: 258,
    // The longest shot in either film. The gate is the argument the product
    // stands on, and it needs the exam to finish, be read, and then be acted on.
    from: at('threequarter', 1.86, 0.012, 0.042),
    to: at('threequarter', 1.6, 0.004, 0.018),
    ease: 'drift',
    tail: 132,
  },
  {
    id: 'safety',
    // The near-profile, because this view is full-width bands stacked down the
    // display. On the three-quarter the glass drops 17% of its width from left
    // to right, so a band's left edge sits higher on screen than the band above
    // it does on the right, and the two read as overlapping. The profile drops
    // 5% and the stack holds together.
    mockup: 'side',
    duration: 216,
    from: at('side', 1.92, 0.058, 0.046),
    to: at('side', 1.7, 0.044, 0.024),
    ease: 'drift',
    tail: 116,
  },
  {
    id: 'brain',
    mockup: 'top',
    duration: 234,
    from: at('top', 1.6, -0.004, 0.002),
    to: at('top', 1.88, 0.012, 0.02),
    ease: 'drift',
    tail: 104,
  },

  /* ---- the close: the same shot as `brain`, pulled back --------------- */
  {
    id: 'close',
    mockup: 'top',
    duration: 294,
    from: at('top', 1.88, 0.012, 0.02),
    to: {cx: 0.3, cy: 0.45, w: 1.16},
    ease: 'settle',
    tail: 24,
  },
]);

export const FILM_FRAMES = filmLength(SHOTS);

/** Where the character hands the screen over to the app. */
const HANDOFF = 322;
const HANDOFF_LEN = 46;

/**
 * What is on the glass in each shot, and the film frame its own clock starts
 * from. See `ArslanShort` for why this is film-relative rather than
 * shot-relative — the short answer is that `brain` and `close` are one take, and
 * a shot-relative clock rebuilds the graph halfway through it.
 */
const SCREENS: Record<
  string,
  {view: 'opening' | 'thread' | 'spawns' | 'promotion' | 'safety' | 'brain'; since: number}
> = {
  open: {view: 'opening', since: 0},
  reveal: {view: 'opening', since: 0},
  settle: {view: 'opening', since: 0},
  thread: {view: 'thread', since: HANDOFF},
  spawns: {view: 'spawns', since: 588},
  promotion: {view: 'promotion', since: 736},
  safety: {view: 'safety', since: 1032},
  brain: {view: 'brain', since: 1240},
  close: {view: 'brain', since: 1240},
};

const OpeningScreen: React.FC<{frame: number}> = ({frame}) => {
  const clip = interpolate(frame, [HANDOFF, HANDOFF + HANDOFF_LEN], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill style={{background: '#FAFBFC'}}>
      {clip < 1 ? <ScreenThread frame={frame - HANDOFF} extended /> : null}
      {clip > 0 ? (
        <AbsoluteFill style={{opacity: clip}}>
          <OffthreadVideo
            src={staticFile(CHARACTER_OPEN.src)}
            muted
            style={{width: SCREEN.w, height: SCREEN.h, objectFit: 'cover'}}
          />
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};

const Screen: React.FC<{id: string; frame: number}> = ({id, frame}) => {
  const spec = SCREENS[id];
  const t = frame - spec.since;
  switch (spec.view) {
    case 'opening':
      return <OpeningScreen frame={t} />;
    case 'thread':
      return <ScreenThread frame={t} extended />;
    case 'spawns':
      return <ScreenSpawns frame={t} />;
    case 'promotion':
      return <ScreenPromotion frame={t} />;
    case 'safety':
      return <ScreenSafety frame={t} />;
    default:
      return <ScreenBrain frame={t} />;
  }
};

export const ArslanFilm: React.FC = () => {
  const frame = useCurrentFrame();
  const {shot, t} = shotAt(SHOTS, frame);
  const view = viewAt(shot, t);

  return (
    <AbsoluteFill style={{background: MOCKUPS[shot.mockup].void, overflow: 'hidden'}}>
      <Mockup mockup={shot.mockup} view={view}>
        <Screen id={shot.id} frame={frame} />
      </Mockup>
      <Cta start={FILM_FRAMES - 142} />
    </AbsoluteFill>
  );
};
