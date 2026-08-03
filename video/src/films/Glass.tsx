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
  useVideoConfig,
} from 'remotion';
import {FILM_FRAMES, SHOTS} from '../ArslanFilm';
import {glassBox, type MockupName} from '../components/Mockup';
import {filmLength, sequence} from '../lib/shots';
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
 * Covered, not contained — see the note on the fit below.
 *
 * `drift` is what stops the screen being a photograph. It is small on purpose —
 * a few per cent over a whole shot — because the camera is already moving, and
 * two moves fighting each other is what made the earliest cut read as slides.
 */
const Plate: React.FC<{src: string}> = ({src}) => {
  const p = plateSize(src);
  // Contain, and no push. Both follow from the same fact: a screenshot is a
  // window that runs to its own edges, so anything that scales it up crops the
  // chrome first — the traffic lights, the left rail, SYNTHESIZE SPAWN. Cover
  // costs 2.5% a side before any move; a 4% drift costs another 2%; together
  // that took the sidebar labels off. The screen already moves, because the
  // camera moves and the cursor moves, and it does not need a third motion
  // paid for in cropped interface.
  //
  // Containing used to leave a visible band, which is why cover was tried at
  // all. That band was never the plate: it was the mock-up's own bright screen
  // showing between the measured quad and the bezel, and `Mockup`'s `bleed`
  // fixes it at the source. The bands are now the same near-black as the app.
  const fit = Math.min(SCREEN.w / p.w, SCREEN.h / p.h);
  const w = p.w * fit;
  const h = p.h * fit;
  return (
    <AbsoluteFill style={{overflow: 'hidden', background: '#0B0F14'}}>
      <Img
        src={staticFile(src)}
        style={{
          position: 'absolute',
          left: (SCREEN.w - w) / 2,
          top: (SCREEN.h - h) / 2,
          width: w,
          height: h,
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

const HANDOFF_LEN = 52;

/**
 * The opening: the character full bleed, handing off to the first real screen.
 * The clip is 2K now, so at full glass width it is running under its native
 * size instead of over it for the first time in this film's life.
 */
const Opening: React.FC<{f: number; at: number; to: string; len: number}> = ({
  f,
  at,
  to,
  len,
}) => {
  const out = ramp(f, at, len);
  return (
    <AbsoluteFill style={{background: '#0B0F14', overflow: 'hidden'}}>
      {out > 0 ? (
        <AbsoluteFill
          style={{
            opacity: Math.min(1, out * 2),
            filter: `blur(${(1 - out) * 16}px) brightness(${1 + (1 - out) * 1.1})`,
          }}
        >
          <Plate src={to} />
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
const VIEWS: Record<string, {src: string}> = {
  thread: {src: 'rec/chat.jpg'},
  spawns: {src: 'rec/ledger.jpg'},
  promotion: {src: 'rec/create.jpg'},
  safety: {src: 'rec/auto.jpg'},
  brain: {src: 'rec/brain.jpg'},
  close: {src: 'rec/brain.jpg'},
};

/** Where the pointer goes on each page, in 1600x1106 screen space. */
const PATHS: Record<string, {path: [number, number][]; clicks: number[]}> = {
  thread: {path: [[980, 830], [1180, 700], [1240, 250]], clicks: [118, 196]},
  spawns: {path: [[420, 300], [700, 520], [1120, 540]], clicks: [118, 196]},
  promotion: {path: [[520, 360], [820, 640], [1300, 900]], clicks: [118, 196, 274]},
  safety: {path: [[520, 560], [1180, 400], [1180, 690]], clicks: [118, 196]},
  brain: {path: [[900, 520], [1080, 620]], clicks: [118]},
};

const Screen: React.FC<{
  id: string;
  f: number;
  since: number;
  handoff: {at: number; to: string; len: number};
}> = ({id, f, since, handoff}) => {
  if (id === 'open' || id === 'reveal' || id === 'settle')
    return <Opening f={f} at={handoff.at} to={handoff.to} len={handoff.len} />;
  const v = VIEWS[id] ?? VIEWS.brain;
  const p = PATHS[id];
  const t = f - since;
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      <Plate src={v.src} />
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

/**
 * Both cuts render through this. `frame` is taken from the composition rather
 * than assumed, so the same code lays out correctly at 1920x1080 and at
 * 2560x1440 — the mock-up maths is all normalised, and the only thing that was
 * hard-coded to 1080p was the call to action, which is scaled to suit.
 */
const Film: React.FC<{
  shots: typeof SHOTS;
  since: Record<string, number>;
  ctaAt: number;
  handoff: {at: number; to: string; len: number};
  /**
   * Multiplies every shot's width. Below 1 the camera sits closer.
   *
   * A 3:4 frame is 44% narrower than 16:9 at the same height, and the mock-up
   * maths is normalised to frame WIDTH — so reusing the landscape framing puts
   * the machine at the same fraction of a much narrower frame, which is a much
   * smaller machine, with the plate's own top and bottom edges showing as bands
   * either side of it. Closing in fixes both at once: the screen fills the
   * width and the glass covers the frame.
   */
  tighten?: number;
}> = ({shots, since, ctaAt, handoff, tighten = 1}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();
  const {shot, t} = shotAt(shots, frame);
  const raw = viewAt(shot, t);
  const view = tighten === 1 ? raw : {...raw, w: raw.w * tighten};
  const k = width / 1920;

  return (
    <AbsoluteFill style={{background: MOCKUPS[shot.mockup].void, overflow: 'hidden'}}>
      <Mockup
        mockup={shot.mockup}
        view={view}
        frame={{w: width, h: height}}
        bleed={1.012}
      >
        <Screen id={shot.id} f={frame} since={since[shot.id] ?? 0} handoff={handoff} />
      </Mockup>
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          width: 1920,
          height: 1080,
          transform: `scale(${k})`,
          transformOrigin: '0 0',
        }}
      >
        <Cta start={ctaAt} />
      </div>
    </AbsoluteFill>
  );
};

export const Glass: React.FC = () => (
  <Film
    shots={SHOTS}
    since={SINCE}
    ctaAt={GLASS_FRAMES - 142}
    handoff={{at: 322, to: 'rec/home.jpg', len: HANDOFF_LEN}}
  />
);

/* ================================================================== */
/* The fifteen                                                         */

/**
 * Three product screens, not six.
 *
 * The 60 has eight shots and at a quarter of the length that would be a screen
 * change every two seconds — which is the wrong trade twice over. It gives no
 * page long enough to be read, and every change is another chance for the join
 * between the screenshot and the glass to be noticed. Fewer, longer holds are
 * both calmer and harder to catch out.
 *
 * The opening keeps its full share. The pull-back out of the character is the
 * only moment in any of these films where something is revealed rather than
 * shown, and cutting it to fit is how a short film becomes a slideshow.
 */
const at15 = (m: MockupName, out: number, dx = 0, dy = 0) => {
  const b = glassBox(m);
  return {
    cx: (b.x0 + b.x1) / 2 + dx,
    cy: (b.y0 + b.y1) / 2 + dy,
    w: (b.x1 - b.x0) * out,
  };
};

export const SHOTS_15 = sequence([
  {
    id: 'open',
    mockup: 'front' as MockupName,
    duration: 54,
    from: at15('front', 0.8),
    to: at15('front', 0.95, 0, 0.003),
    ease: 'ease' as const,
    tail: 40,
  },
  {
    id: 'reveal',
    mockup: 'front' as MockupName,
    duration: 72,
    from: at15('front', 0.95, 0, 0.003),
    to: at15('front', 2.28, 0, 0.055),
    ease: 'ease' as const,
    tail: 22,
  },
  {
    id: 'thread',
    mockup: 'threequarter' as MockupName,
    duration: 76,
    from: at15('threequarter', 1.88, 0.014, 0.046),
    to: at15('threequarter', 1.68, 0.006, 0.024),
    ease: 'drift' as const,
    tail: 54,
  },
  {
    id: 'spawns',
    mockup: 'front' as MockupName,
    duration: 76,
    from: at15('front', 1.88, 0, 0.03),
    to: at15('front', 1.7, 0, 0.018),
    ease: 'drift' as const,
    tail: 54,
  },
  {
    id: 'safety',
    mockup: 'threequarter' as MockupName,
    duration: 74,
    from: at15('threequarter', 1.84, 0.012, 0.042),
    to: at15('threequarter', 1.62, 0.004, 0.02),
    ease: 'drift' as const,
    tail: 48,
  },
  {
    id: 'close',
    mockup: 'top' as MockupName,
    duration: 98,
    from: at15('top', 1.9, 0, 0.02),
    to: at15('top', 3.05, 0.055, 0.012),
    ease: 'settle' as const,
  },
]);

export const GLASS15_FRAMES = filmLength(SHOTS_15);

/** Every view restarts at its own cut — nothing is carried across in the 15. */
const SINCE_15: Record<string, number> = {
  thread: 126,
  spawns: 202,
  safety: 278,
  close: 352,
};

export const Glass15: React.FC = () => (
  <Film
    shots={SHOTS_15}
    since={SINCE_15}
    ctaAt={380}
    // The character gives way inside the pull-back rather than after it, so the
    // machine is already showing the client by the time it is fully revealed.
    handoff={{at: 92, to: 'rec/chat.jpg', len: 34}}
  />
);

/**
 * The 3:4 cut, for a Xiaohongshu feed. Same film, closer camera.
 *
 * A 16:9 note is shown letterboxed and small there, and small is fatal on a
 * platform where the first frame is the whole pitch — so this is a reframe
 * rather than a crop of the landscape render, which would have cut the screen
 * in half on every shot.
 */
export const Glass15V: React.FC = () => (
  <Film
    shots={SHOTS_15}
    since={SINCE_15}
    ctaAt={380}
    handoff={{at: 92, to: 'rec/chat.jpg', len: 34}}
    tighten={0.6}
  />
);
