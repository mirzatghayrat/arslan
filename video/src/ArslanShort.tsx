import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {ScreenBrain, ScreenPromotion, ScreenThread} from './components/AppScreen';
import {Cta} from './components/Cta';
import {glassBox, Mockup, MOCKUPS, SCREEN, type MockupName} from './components/Mockup';
import {filmLength, sequence, shotAt, viewAt} from './lib/shots';
import {CHARACTER_OPEN} from './lightTheme';

/**
 * The 30-second cut. Fast, and meant to make someone stop scrolling.
 *
 * The spine is the one the brief asked for: the character fills the frame, the
 * camera pulls back until a bezel arrives and it turns out to have been a
 * screen, the app takes that screen over, and the last pull-back opens clear
 * set beside the machine for the download.
 *
 * Two of these shots are really one shot each. The opening is a single
 * uninterrupted pull-back — the character never stops playing through it, and
 * the app takes the screen by dissolving underneath the same move rather than
 * after a cut. The close is the same: the film does not cut to the call to
 * action, it pulls back until there is room for it. Everything between is a
 * hard cut, and no shot ever comes to rest before one — see `tail` in
 * `lib/shots`.
 *
 * `ArslanFilm` is the 60, which is the same story with a different shot
 * language rather than this one stretched.
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
  /* ---- one continuous pull-back, 0 to 200 ---------------------------- */
  {
    id: 'open',
    mockup: 'front',
    duration: 108,
    // Starts inside the glass and barely creeps, so the first three seconds are
    // the character and nothing else. The reveal has to be earned.
    from: at('front', 0.8),
    to: at('front', 1.02, 0, 0.004),
    ease: 'ease',
    tail: 44,
  },
  {
    id: 'reveal',
    mockup: 'front',
    duration: 92,
    // Bezel, lid, deck, linen. Arrives on the machine and keeps travelling
    // into the cut.
    from: at('front', 1.02, 0, 0.004),
    to: at('front', 2.46, 0, 0.06),
    ease: 'ease',
    tail: 30,
  },

  /* ---- the app, three cuts ------------------------------------------- */
  {
    id: 'thread',
    mockup: 'threequarter',
    duration: 158,
    from: at('threequarter', 1.94, 0.016, 0.05),
    to: at('threequarter', 1.68, 0.008, 0.024),
    ease: 'drift',
    tail: 72,
  },
  {
    id: 'promotion',
    mockup: 'side',
    duration: 168,
    from: at('side', 2.02, 0.062, 0.05),
    to: at('side', 1.76, 0.048, 0.026),
    ease: 'drift',
    tail: 76,
  },
  {
    id: 'brain',
    mockup: 'top',
    duration: 156,
    from: at('top', 1.64, -0.002, 0.004),
    to: at('top', 1.9, 0.012, 0.022),
    ease: 'drift',
    tail: 68,
  },

  /* ---- the close: the same shot as `brain`, pulled back --------------- */
  {
    id: 'close',
    mockup: 'top',
    duration: 218,
    from: at('top', 1.9, 0.012, 0.022),
    to: {cx: 0.3, cy: 0.45, w: 1.16},
    ease: 'settle',
    tail: 30,
  },
]);

export const SHORT_FRAMES = filmLength(SHOTS);

/** Where the character hands the screen over to the app. */
const HANDOFF = 118;
const HANDOFF_LEN = 38;

/**
 * What is on the glass in each shot, and the film frame its own clock starts
 * from.
 *
 * Two things go wrong if a view is simply started at zero on the cut. The
 * screen spends its first second as an empty white rectangle, which against a
 * warm set reads as an app that has not loaded rather than one doing something;
 * and a view carried across a cut — the second brain, which the close holds on
 * while the camera pulls back — restarts, so the graph the viewer just watched
 * form dissolves and builds again.
 *
 * Giving each shot the film frame its view zeroed at fixes both. `brain` and
 * `close` share one, because they are one continuous take. The others are set
 * back far enough that the cut lands on something already legible, leaving the
 * payoff — the chart growing, the gate being pressed — to happen on screen.
 */
const SCREENS: Record<string, {view: 'opening' | 'thread' | 'promotion' | 'brain'; since: number}> = {
  open: {view: 'opening', since: 0},
  reveal: {view: 'opening', since: 0},
  thread: {view: 'thread', since: HANDOFF},
  promotion: {view: 'promotion', since: 292},
  brain: {view: 'brain', since: 486},
  close: {view: 'brain', since: 486},
};

/**
 * The opening screen: the clip, then the app, on the same glass under the same
 * move.
 *
 * The dissolve is what makes the reveal land. Cutting here would say "and now,
 * some software"; a dissolve says the thing you have been looking at was on
 * this machine the whole time.
 */
const OpeningScreen: React.FC<{frame: number}> = ({frame}) => {
  const clip = interpolate(frame, [HANDOFF, HANDOFF + HANDOFF_LEN], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill style={{background: '#FAFBFC'}}>
      {clip < 1 ? <ScreenThread frame={frame - HANDOFF} /> : null}
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
      return <ScreenThread frame={t} />;
    case 'promotion':
      return <ScreenPromotion frame={t} />;
    default:
      return <ScreenBrain frame={t} />;
  }
};

export const ArslanShort: React.FC = () => {
  const frame = useCurrentFrame();
  const {shot, t} = shotAt(SHOTS, frame);
  const view = viewAt(shot, t);

  return (
    <AbsoluteFill style={{background: MOCKUPS[shot.mockup].void, overflow: 'hidden'}}>
      <Mockup mockup={shot.mockup} view={view}>
        <Screen id={shot.id} frame={frame} />
      </Mockup>
      <Cta start={SHORT_FRAMES - 150} />
    </AbsoluteFill>
  );
};
