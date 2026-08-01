import React from 'react';
import {AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {PRODUCT, SAFETY, SPAWNS} from '../facts';
import {font} from '../theme';

/**
 * FILM 6 — "RUNWAY". Built from a named shot list rather than chosen freely,
 * and from real screen capture rather than drawn UI.
 *
 * Eight cards, in this order: `spotlight-hero-card` → `neon-frame-forerun` →
 * `graze-face-tour` → `steep-tilt-glide` → `page-waterfall-wall` →
 * `runway-ground-skim` → `neon-frame-orbit-drop`, with `shot-transitions` A
 * (flash-cut) on three of the seams. 36 seconds, because eight signature moves
 * with the holds their cards require do not fit in thirty — several of them
 * specify their own minimum (the spotlight needs 3.3s from lock to landing
 * alone) and compressing them is how you end up with eight moves none of which
 * reads.
 *
 * THE CARDS DISAGREE WITH EACH OTHER ON PURPOSE, and getting it wrong is an
 * explicit rejection in all three. The drop grammar is different in every shot
 * that has one:
 *   - `graze-face-tour` — a tour. Starts staggered, falls overlap in parallel.
 *   - `runway-ground-skim` — a downpour. Starts only 1.5f apart, 9f of gravity,
 *     five or six in the air at once, and ZERO bounce on landing.
 *   - `neon-frame-orbit-drop` — an ensemble debut. Every element leaves, falls
 *     and lands on the SAME FRAME. Any stagger at all turns it into a tour.
 * Two other pairs are marked never-adjacent: the two neon frames are the same
 * language twice, so they open and close the film with five shots between them;
 * and `graze-face-tour` moves the camera over a still page while
 * `steep-tilt-glide` locks the camera and moves the page, so they are separated
 * by a flash cut rather than run together.
 *
 * ON THE FOOTAGE. Every frame in this film is the real client — nothing here is
 * drawn UI. The capture is 480p, upscaled to 1280x872 plates, and it holds to
 * about 1.7x: a full page at ~1100px reads fine, which is what the shots are
 * built around — slices on a receding wall, a page foreshortened at 60 degrees,
 * cards small under a low camera.
 *
 * The opening is the shot that costs. `spotlight-hero-card` wants a hard push
 * onto a single card, and a ledger card is only 276x282 in the plate, so the
 * push is held to 1.6x of a page already at 1.17x — about 2.2x of source on the
 * hero card, which is soft but legible, and it is a dark scene with one lit
 * region so softness reads as depth. A first version drew that card in code to
 * dodge the upscale; it looked better frozen and worse moving, because the cut
 * to real footage 165 frames later gave the whole trick away. Real and slightly
 * soft beats sharp and fake. An HD capture would let the push go where the card
 * actually asks (2.6x) — this is the one shot that would gain from it.
 */

const N = {
  bg: '#05070B',
  ink: '#E9EEF6',
  dim: '#8792A3',
  faint: '#4A5361',
  neon: '#FF8A3D',
  neon2: '#5EE7E0',
  violet: '#9B8CFF',
};

export const RUNWAY_FRAMES = 1080;

const ramp = (f: number, s: number, l: number, e = Easing.out(Easing.cubic)) =>
  interpolate(f, [s, s + l], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: e,
  });

/** Deterministic. Math.random would differ between render passes. */
const jit = (k: number, m: number) => ((k * 7919) % (2 * m + 1)) - m;

/* ================================================================== */
/* The capture, and slices of it                                       */

const SRC = {w: 1280, h: 872};

/**
 * A rectangle of the capture, in SOURCE pixel coordinates, drawn at `w` wide.
 *
 * Slicing rather than showing whole pages is what makes the drop shots possible
 * at all: a screen recording is one flat image, so "components falling from
 * above" has to be regions of that image moving independently. It is also what
 * the waterfall card asks for directly — card-level blocks, because whole-page
 * slices scroll past faster than anyone can read them.
 */
type Rect = {x: number; y: number; w: number; h: number};

const Slice: React.FC<{
  src: string;
  rect: Rect;
  w: number;
  style?: React.CSSProperties;
}> = ({src, rect, w, style}) => {
  const k = w / rect.w;
  return (
    <div
      style={{
        width: w,
        height: rect.h * k,
        ...style,
        // after the spread, never before: a caller reaching for the `background`
        // shorthand to set a backing colour resets `background-image` to none,
        // and the slice renders as an empty rectangle with a border on it
        backgroundImage: `url(${staticFile(src)})`,
        backgroundSize: `${SRC.w * k}px ${SRC.h * k}px`,
        backgroundPosition: `${-rect.x * k}px ${-rect.y * k}px`,
      }}
    />
  );
};

/**
 * The floating element with its own shadow, shared by four of the eight cards.
 *
 * `h` is height above the surface in surface pixels. Everything about the
 * shadow tracks it — it grows, blurs and fades as the element rises, and at
 * h = 0 it coincides with the element and disappears. The cards are unanimous
 * and repetitive on this point: a shadow that does not track height reads as a
 * sticker, and no shadow at all means the float was never made. Airborne
 * elements are also lifted about 1.3x in brightness, because a dark scene
 * swallows them otherwise and an invisible float is the same as no float.
 */
/**
 * `axis` is not a style choice. On a page facing the camera, "up" is up the
 * screen and `translateY` is the lift; on a ground plane the same translateY
 * slides the element backwards along the floor, which reads as receding rather
 * than rising, and only `translateZ` comes off the surface. The z form needs an
 * unbroken `preserve-3d` chain to the perspective root — `overflow: hidden`
 * anywhere above it flattens the scene and silently kills the lift, which is
 * why the framed shots use y and the ground shots use z.
 */
const FloatWrap: React.FC<{
  h: number;
  children: React.ReactNode;
  maxH?: number;
  axis?: 'y' | 'z';
}> = ({h, children, maxH = 180, axis = 'y'}) => {
  const t = Math.min(1, Math.max(0, h / maxH));
  return (
    <div style={{position: 'relative', transformStyle: 'preserve-3d'}}>
      {/* the shadow: same shape, cast on the surface below */}
      {t > 0.01 ? (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            transform: `translate(${t * 26}px, ${t * 34}px) scale(${1 + t * 0.05})`,
            filter: `blur(${4 + t * 26}px)`,
            opacity: 0.55 * (1 - t * 0.55),
            background: 'rgba(0,0,0,0.92)',
            borderRadius: 10,
          }}
        />
      ) : null}
      <div
        style={{
          position: 'relative',
          transform: axis === 'z' ? `translateZ(${h}px)` : `translateY(${-h}px)`,
          filter: t > 0.01 ? `brightness(${1 + t * 0.32})` : undefined,
        }}
      >
        {children}
      </div>
    </div>
  );
};

/** Gravity: distance goes as t squared, and it stops dead. No bounce. */
const fall = (f: number, start: number, dur: number) => {
  const t = Math.min(1, Math.max(0, (f - start) / dur));
  return 1 - t * t;
};

/* ================================================================== */
/* Slice tables, in source coordinates of the 1280x872 plates          */

const LEDGER_CARDS: Rect[] = [
  {x: 316, y: 184, w: 276, h: 282},
  {x: 618, y: 184, w: 276, h: 282},
  {x: 922, y: 184, w: 276, h: 282},
  {x: 316, y: 488, w: 276, h: 282},
  {x: 618, y: 488, w: 276, h: 282},
  {x: 922, y: 488, w: 276, h: 282},
];
const LEDGER_HEAD: Rect = {x: 316, y: 110, w: 882, h: 60};
const SIDEBAR: Rect = {x: 52, y: 34, w: 236, h: 768};

/**
 * Tiles for the ground shot, all at 2:1.
 *
 * The first version cut these along the equip dialog's own regions — a header
 * band, a scope band, three columns — and every one of them came out a
 * different shape. Laid on a plane raked past fifty degrees, a 66-pixel-tall
 * band foreshortens to a bright line: six tiles went past the camera and not
 * one of them read as an interface. Everything on the runway is now the same
 * aspect, so the rake affects all of them equally and the eye has something
 * constant to measure the travel against.
 *
 * The equip dialog still carries two of the six, because it is the page that
 * shows what `SPAWNS.equip` claims — skills, tools and MCP servers as three
 * separate columns you tick — and that is the caption on this shot.
 */
const TILES: {src: string; rect: Rect}[] = [
  {src: 'rec/spawn.jpg', rect: {x: 180, y: 120, w: 900, h: 450}}, // identity + scope + columns
  {src: 'rec/forge.jpg', rect: {x: 320, y: 400, w: 880, h: 440}}, // skill packs, row after row
  {src: 'rec/spawn.jpg', rect: {x: 180, y: 280, w: 900, h: 450}}, // SKILLS · TOOLS · MCPS
  {src: 'rec/ledger.jpg', rect: {x: 310, y: 180, w: 890, h: 445}}, // the roster
  {src: 'rec/forge.jpg', rect: {x: 320, y: 150, w: 880, h: 440}}, // import from a repo
  {src: 'rec/replay.jpg', rect: {x: 360, y: 180, w: 560, h: 280}}, // what a run actually did
];

/* ================================================================== */
/* 1. spotlight-hero-card                                              */

/**
 * `spotlight-hero-card`. A wandering pool of light takes four stops before it
 * locks — going straight to the target reads as programmatic — then the camera
 * pushes to a three-quarter, the card rises with an overshoot, hovers on a slow
 * sine, gets two laps of an outline beam (the first fast and bright, the second
 * slow and weak, so it reads as continued scanning rather than a blink), and
 * seats back down.
 *
 * The card's timing note is the part most likely to be got wrong: lock to
 * landing is about 98 frames. A first pass is always faster than this and
 * always feels cheap.
 *
 * The pool is a MASK, not a wash. A translucent white radial laid over a dark
 * scene lifts the black as much as the subject and reads as fog; the same
 * content drawn twice — once dimmed, once at full brightness through a radial
 * mask — is an actual light, and it is the difference between this shot
 * existing and not.
 */

/* The hero card's home position, in screen pixels, at PAGE_K. Everything in the
   shot — the lift, the seat, the beam, the push origin — is derived from this
   one rectangle rather than restated, because they have to agree exactly. */
const PAGE_K = 1500 / SRC.w;
const PAGE_L = 960 - (SRC.w * PAGE_K) / 2;
const PAGE_T = 540 - (SRC.h * PAGE_K) / 2;
const HERO = LEDGER_CARDS[0];
const HERO_BOX = {
  left: PAGE_L + HERO.x * PAGE_K,
  top: PAGE_T + HERO.y * PAGE_K,
  w: HERO.w * PAGE_K,
  h: HERO.h * PAGE_K,
};
const HERO_CX = HERO_BOX.left + HERO_BOX.w / 2;
const HERO_CY = HERO_BOX.top + HERO_BOX.h / 2;

const STOPS = [
  {x: 1480, y: 300, r: 460},
  {x: 1180, y: 820, r: 500},
  {x: 620, y: 760, r: 380},
  // at lock the pool is the pushed card plus a margin, and no more: a pool wide
  // enough to catch the neighbouring cards is not a spotlight, it is a lamp
  {x: HERO_CX, y: HERO_CY, r: 190},
];

const Spotlight: React.FC<{f: number}> = ({f}) => {
  const leg = interpolate(f, [6, 20, 34, 48], [0, 1, 2, 3], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const i = Math.min(STOPS.length - 1, Math.floor(leg));
  const j = Math.min(STOPS.length - 1, i + 1);
  const t = leg - i;
  const px = STOPS[i].x + (STOPS[j].x - STOPS[i].x) * t;
  const py = STOPS[i].y + (STOPS[j].y - STOPS[i].y) * t;
  const lockPulse = ramp(f, 48, 3) * (1 - ramp(f, 51, 9));
  // the pool opens up as the camera pushes, so the card does not outgrow it
  const grow = ramp(f, 34, 46);
  const pr = (STOPS[i].r + (STOPS[j].r - STOPS[i].r) * t) * (1 + lockPulse * 0.08 + grow * 0.6);

  // camera: static wide, then a modest push onto the card and a three-quarter
  const zoom = interpolate(f, [0, 32, 60], [0.94, 0.94, 1.62], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.2, 1),
  });
  const rotY = interpolate(f, [32, 60], [0, 18], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.2, 1),
  });

  // rise (with overshoot) → hover (sine bob) → reseat. ~98f lock to landing.
  const rise = ramp(f, 52, 10, Easing.bezier(0.2, 1.25, 0.3, 1));
  const reseat = ramp(f, 128, 18, Easing.bezier(0.3, 0, 0.2, 1));
  const lift = rise * (1 - reseat);
  const bob = lift * Math.sin(((f - 52) / 40) * Math.PI * 2) * 4;
  const press = f > 144 && f < 150 ? 0.997 : 1;

  const stage = (
    <AbsoluteFill style={{perspective: 1500}}>
      <AbsoluteFill
        style={{
          transform: `scale(${zoom}) rotateY(${rotY}deg)`,
          transformOrigin: `${(HERO_CX / 1920) * 100}% ${(HERO_CY / 1080) * 100}%`,
        }}
      >
        {/* the page the card belongs to */}
        <Img
          src={staticFile('rec/ledger.jpg')}
          style={{
            position: 'absolute',
            left: PAGE_L,
            top: PAGE_T,
            width: SRC.w * PAGE_K,
            height: SRC.h * PAGE_K,
          }}
        />

        {/* where it came from: the seat breathes while the card is up */}
        <div
          style={{
            position: 'absolute',
            left: HERO_BOX.left,
            top: HERO_BOX.top,
            width: HERO_BOX.w,
            height: HERO_BOX.h,
            borderRadius: 12,
            border: `1.5px solid ${N.neon}`,
            opacity: lift * (0.3 + 0.22 * Math.sin(f / 13)),
            background: 'rgba(6,9,13,0.94)',
          }}
        />

        <div
          style={{
            position: 'absolute',
            left: HERO_BOX.left,
            top: HERO_BOX.top,
            transform: `translateY(${-lift * 96 + bob}px) scale(${press})`,
            filter: `drop-shadow(0 ${44 * lift}px ${70 * lift}px rgba(0,0,0,${0.75 * lift}))`,
          }}
        >
          <Slice
            src="rec/ledger.jpg"
            rect={HERO}
            w={HERO_BOX.w}
            style={{borderRadius: 12, border: '1px solid #202A36'}}
          />

          {/* the outline beam: two laps, fast-and-bright then slow-and-weak */}
          <svg
            width={HERO_BOX.w}
            height={HERO_BOX.h}
            style={{position: 'absolute', left: 0, top: 0, pointerEvents: 'none'}}
          >
            {[
              {a: 92, b: 106, w: 4, o: 1},
              {a: 112, b: 132, w: 3, o: 0.6},
            ].map((lap, k) => {
              const p = ramp(f, lap.a, lap.b - lap.a, Easing.inOut(Easing.cubic));
              if (p <= 0 || p >= 1) return null;
              return (
                <rect
                  key={k}
                  x={1}
                  y={1}
                  width={HERO_BOX.w - 2}
                  height={HERO_BOX.h - 2}
                  rx={12}
                  fill="none"
                  stroke={N.neon}
                  strokeWidth={lap.w}
                  opacity={lap.o}
                  pathLength={1}
                  strokeDasharray="0.14 1"
                  strokeDashoffset={-p}
                />
              );
            })}
          </svg>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );

  const pool = `radial-gradient(${pr}px ${pr}px at ${px}px ${py}px, rgba(0,0,0,1) 0%, rgba(0,0,0,0.88) 52%, rgba(0,0,0,0) 74%)`;

  return (
    <AbsoluteFill style={{background: '#020407', overflow: 'hidden'}}>
      {/* everything, pressed down to what a room with the lights off looks like */}
      <AbsoluteFill style={{filter: 'brightness(0.24) saturate(0.75)'}}>{stage}</AbsoluteFill>
      {/* and the same thing again at full strength, but only inside the pool */}
      <AbsoluteFill
        style={{
          maskImage: pool,
          WebkitMaskImage: pool,
          filter: `brightness(${1 + lift * 0.12})`,
        }}
      >
        {stage}
      </AbsoluteFill>
      {/* the beam itself, so the light has a source and not just an effect */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(${pr * 1.05}px ${pr * 1.05}px at ${px}px ${py}px, rgba(255,196,140,0.055) 0%, rgba(255,196,140,0.02) 52%, rgba(0,0,0,0) 78%)`,
        }}
      />

      <Caption f={f} at={112} text="One spawn. You raised it, you equipped it." />
    </AbsoluteFill>
  );
};

/* ================================================================== */
/* 2. neon-frame-forerun                                               */

/**
 * The neon frame, run out from the middle of the left edge in both directions
 * at once. Drawing it from one end reads as someone drawing a diagram; running
 * it from the middle reads as runway lighting, which is the whole idea — the
 * frame announces where something is about to be.
 */
const NeonFrame: React.FC<{
  f: number;
  start: number;
  w: number;
  h: number;
  dur?: number;
  colour?: string;
}> = ({f, start, w, h, dur = 18, colour = N.neon}) => {
  const p = ramp(f, start, dur, Easing.out(Easing.cubic));
  if (p <= 0) return null;
  return (
    <svg width={w} height={h} style={{position: 'absolute', left: 0, top: 0, overflow: 'visible'}}>
      <defs>
        <filter id="nfglow" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="7" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      {[1, -1].map((dir) => (
        <path
          key={dir}
          d={
            dir === 1
              ? `M 1 ${h / 2} V 1 H ${w - 1} V ${h - 1} H 1 Z`
              : `M 1 ${h / 2} V ${h - 1} H ${w - 1} V 1 H 1 Z`
          }
          fill="none"
          stroke={colour}
          strokeWidth={3}
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - p * 0.5}
          filter="url(#nfglow)"
          opacity={0.95}
        />
      ))}
      <rect
        x={1}
        y={1}
        width={w - 2}
        height={h - 2}
        fill="none"
        stroke={colour}
        strokeWidth={2}
        opacity={p >= 1 ? ramp(f, start + dur, 40) * 0.55 : 0}
        filter="url(#nfglow)"
      />
    </svg>
  );
};

/**
 * `neon-frame-forerun`. Frame first, then the page lights inside it, and the
 * components drop in staggered but overlapping — the tour grammar, because the
 * camera is static here and the page is being filled in region by region.
 * The drop window runs with the lighting window and finishes about 20 frames
 * after it; landing furniture in a dark room is the failure the card names.
 */
const Forerun: React.FC<{f: number}> = ({f}) => {
  const W = 1180;
  const H = 804;
  const lit = ramp(f, 22, 54);
  return (
    <AbsoluteFill style={{background: N.bg, overflow: 'hidden'}}>
      {/* background neon tubes, which dim at the end to give up the brightness */}
      {[0, 1, 2, 3].map((k) => {
        const out = 1 - ramp(f, 96 + (k === 1 || k === 2 ? 0 : 10), 22);
        return (
          <div
            key={k}
            style={{
              position: 'absolute',
              left: 90 + k * 470,
              top: -120,
              width: 3,
              height: 1320,
              background: k % 2 ? N.neon2 : N.violet,
              opacity: 0.16 * ramp(f, 4 + k * 3, 16) * out,
              filter: 'blur(3px)',
              transform: `rotate(${8 + k * 2}deg)`,
            }}
          />
        );
      })}

      <AbsoluteFill style={{perspective: 1400}}>
        <div
          style={{
            position: 'absolute',
            left: 960 - W / 2,
            top: 540 - H / 2,
            width: W,
            height: H,
            transformStyle: 'preserve-3d',
            transform: 'rotateY(-13deg) rotateX(4deg)',
          }}
        >
          <NeonFrame f={f} start={4} w={W} h={H} />

          <div
            style={{
              position: 'absolute',
              inset: 10,
              overflow: 'hidden',
              background: '#080B10',
              filter: `brightness(${0.22 + lit * 0.78})`,
            }}
          >
            {/* sidebar drops first, then the header, then the cards in reading
                order — starts staggered, falls overlapping. */}
            <div style={{position: 'absolute', left: 0, top: 0}}>
              <FloatWrap h={fall(f, 34, 26) * 140}>
                <Slice src="rec/ledger.jpg" rect={SIDEBAR} w={214} />
              </FloatWrap>
            </div>
            <div style={{position: 'absolute', left: 236, top: 26}}>
              <FloatWrap h={fall(f, 44, 26) * 140}>
                <Slice src="rec/ledger.jpg" rect={LEDGER_HEAD} w={880} />
              </FloatWrap>
            </div>
            {LEDGER_CARDS.map((r, k) => (
              <div
                key={k}
                style={{
                  position: 'absolute',
                  left: 236 + (k % 3) * 298,
                  top: 110 + Math.floor(k / 3) * 304,
                }}
              >
                <FloatWrap h={fall(f, 52 + k * 7, 28) * 150}>
                  <Slice src="rec/ledger.jpg" rect={r} w={286} />
                </FloatWrap>
              </div>
            ))}
          </div>
        </div>
      </AbsoluteFill>

      <Caption f={f} at={88} text="A roster you build, not one that ships." />
    </AbsoluteFill>
  );
};

/* ================================================================== */
/* 3. graze-face-tour                                                  */

/**
 * `graze-face-tour`. The camera flies low along the page as if it were terrain,
 * at an angle steep enough that the sidebar and the rows become landscape.
 * Depth of field is part of the grammar rather than decoration — everything
 * sharp reads as a flat scroll.
 */
const Graze: React.FC<{f: number}> = ({f}) => {
  const travel = interpolate(f, [0, 138], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.35, 0, 0.4, 1),
  });
  return (
    <AbsoluteFill style={{background: N.bg, overflow: 'hidden'}}>
      <AbsoluteFill style={{perspective: 1150, perspectiveOrigin: '44% 24%'}}>
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 210,
            width: 6200,
            transformStyle: 'preserve-3d',
            // 52 degrees, not 70-something. A grazing angle steep enough that the
            // page becomes terrain still has to leave the tiles tall enough to be
            // recognisable as an interface; past about 60 they collapse into a
            // bright line at the horizon and the shot is showing nothing.
            // stops with two tiles still on the runway rather than running off
            // the end of the strip — the camera has to still be travelling at
            // the cut, not sitting in front of the last panel waiting
            transform: `rotateX(52deg) rotateZ(-5deg) translateX(${-travel * 3000}px)`,
            transformOrigin: 'left top',
          }}
        >
          <div style={{position: 'relative', width: 6200, height: 1000, transformStyle: 'preserve-3d'}}>
            {/* the runway itself, under everything */}
            <div
              style={{
                position: 'absolute',
                left: 0,
                top: 200,
                width: 6200,
                height: 520,
                background:
                  'linear-gradient(90deg, rgba(255,138,61,0.05), rgba(94,231,224,0.05), rgba(255,138,61,0.05))',
                borderTop: '1px solid rgba(255,138,61,0.28)',
                borderBottom: '1px solid rgba(94,231,224,0.18)',
              }}
            />

            {/* tiles land as the camera reaches them: staggered starts, and the
                falls overlap. Serial waiting is rejected by the card. */}
            {TILES.map((t, k) => {
              const cue = 10 + k * 14;
              return (
                <div
                  key={k}
                  style={{
                    position: 'absolute',
                    // local y ~200 puts the tile in the near half of the plane.
                    // Near the plane's own top edge it is at the vanishing point,
                    // where a tile is thirty pixels tall and the shot is a strip
                    // of light with nothing in it.
                    left: 240 + k * 800,
                    top: 250 + jit(k, 25),
                    transformStyle: 'preserve-3d',
                  }}
                >
                  <FloatWrap h={fall(f, cue, 30) * 200} maxH={220} axis="z">
                    <Slice
                      src={t.src}
                      rect={t.rect}
                      w={760}
                      style={{
                        borderRadius: 12,
                        border: '1px solid #2C3846',
                        backgroundColor: '#0B0F15',
                        // the scene has no light of its own; the plates are dark
                        // UI on a dark set and need lifting to read at all
                        filter: 'brightness(1.4)',
                        boxShadow: '0 0 60px rgba(120,160,255,0.06)',
                      }}
                    />
                  </FloatWrap>
                </div>
              );
            })}
          </div>
        </div>
      </AbsoluteFill>

      {/* Shallow depth of field. It has to be confined to the far distance —
          the top third, above where the tiles sit. An earlier version faded
          from 42% of frame height upward, which is exactly where the subject
          is, and quietly painted the entire shot out. */}
      <AbsoluteFill
        style={{
          background: 'linear-gradient(180deg, rgba(5,7,11,0.95) 0%, rgba(5,7,11,0.5) 16%, rgba(5,7,11,0) 30%)',
          backdropFilter: 'blur(2.5px)',
          maskImage: 'linear-gradient(180deg, black 0%, black 14%, transparent 30%)',
          WebkitMaskImage: 'linear-gradient(180deg, black 0%, black 14%, transparent 30%)',
        }}
      />
      {/* and the near foreground, which is past the focal plane the other way */}
      <AbsoluteFill
        style={{
          background: 'linear-gradient(0deg, rgba(5,7,11,0.85) 0%, rgba(5,7,11,0) 16%)',
        }}
      />

      <Caption f={f} at={96} text={`Equip it: ${SPAWNS.equip}`} />
    </AbsoluteFill>
  );
};

/* ================================================================== */
/* 4. steep-tilt-glide                                                 */

/**
 * `steep-tilt-glide`. The camera is nailed down — perspective, origin and
 * rotation are constants for the whole shot — and the page slides along its own
 * horizontal axis past the lens. The card is emphatic that a camera move here
 * changes the meaning from "the page is showing itself" to "look at my camera
 * work", and that the angle is 60 degrees exactly after three rounds of
 * argument about it.
 */
// Four dense pages. The Capability Library's landing state is mostly empty set,
// and an empty page sliding past at this angle is a dead second.
const GLIDE_PAGES = ['rec/home.jpg', 'rec/forge.jpg', 'rec/replay.jpg', 'rec/diag.jpg'];
const GLIDE_W = 1180;
const GLIDE_H = 804;
const GLIDE_GAP = 90;
const GLIDE_STEP = GLIDE_W + GLIDE_GAP;

const Glide: React.FC<{f: number}> = ({f}) => {
  // travel measured in page-steps, so the pages arrive on the beat rather than
  // wherever a hand-picked pixel range happens to put them
  const at = (g: number) =>
    interpolate(g, [0, 138], [1, -GLIDE_PAGES.length], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      // the tail deliberately does not flatten to zero — a dead stop reads as a stall
      easing: Easing.bezier(0.3, 0.12, 0.72, 0.9),
    }) * GLIDE_STEP;
  const slide = at(f);
  const prev = at(f - 3);
  const speed = Math.abs(slide - prev);
  // fast: the pages are already sliding when the shot opens, and a slow fade-up
  // spends the first second of a 4.8-second shot on nothing
  const lit = ramp(f, 0, 22);

  const strip = (style?: React.CSSProperties) => (
    <div
      style={{
        position: 'absolute',
        left: 0,
        top: 0,
        display: 'flex',
        flexDirection: 'row',
        gap: GLIDE_GAP,
        ...style,
      }}
    >
      {GLIDE_PAGES.map((p, k) => (
        <div key={p} style={{position: 'relative', flexShrink: 0}}>
          <Img src={staticFile(p)} style={{width: GLIDE_W, height: GLIDE_H, display: 'block'}} />
          <div
            style={{position: 'absolute', inset: 0, border: `1px solid ${k % 2 ? N.neon2 : N.neon}55`}}
          />
        </div>
      ))}
    </div>
  );

  return (
    <AbsoluteFill style={{background: N.bg, overflow: 'hidden'}}>
      {/* CAMERA CONSTANTS — none of these may vary with f. The rotation is about
          the centre of a page-sized window at frame centre, not about the far
          end of the strip: pivoting on the strip's own left edge sends every
          page after the first into the distance and the shot becomes a wall
          seen edge-on. */}
      <AbsoluteFill style={{perspective: 1500, perspectiveOrigin: '50% 50%'}}>
        <div
          style={{
            position: 'absolute',
            left: 960 - GLIDE_W / 2,
            top: 540 - GLIDE_H / 2,
            width: GLIDE_W,
            height: GLIDE_H,
            transformStyle: 'preserve-3d',
            transform: 'rotateY(-46deg) rotateZ(-2deg)',
          }}
        >
          {/* speed ghosts: the page as it was 3 and 6 frames ago */}
          {[
            {d: 3, o: 0.3},
            {d: 6, o: 0.16},
          ].map((g) =>
            React.cloneElement(
              strip({
                transform: `translateX(${slide + (slide - prev) * (g.d / 3)}px)`,
                opacity: Math.min(1, speed / 26) * g.o,
                filter: 'blur(2px)',
              }),
              {key: g.d}
            )
          )}

          {strip({
            transform: `translateX(${slide}px)`,
            filter: `brightness(${0.34 + lit * 0.66})`,
          })}
        </div>
      </AbsoluteFill>

      <Caption f={f} at={100} text="Ask · skills · replay · diagnostics — one machine." />
    </AbsoluteFill>
  );
};

/* ================================================================== */
/* 5. page-waterfall-wall                                              */

/**
 * `page-waterfall-wall`. Three columns of card slices on a wall tilted away
 * from the camera, scrolling at different rates with the middle one reversed.
 * Matching rates and directions would read as one big image sliding; the
 * difference is the only evidence that these are independent columns.
 *
 * This is an atmosphere shot, not an information shot — the slices only have to
 * look like real pages, not be readable. It appears once. Twice reads as
 * padding.
 */
const COLS: {loop: number; dir: number; src: string; rects: Rect[]}[] = [
  // All three columns crop at roughly the same width, so all three land at the
  // same zoom on the wall. A single ledger card is 276 source pixels; shown in
  // a 560-wide column beside two 880-wide crops it is twice their scale, and
  // the wall stops reading as one surface.
  {
    loop: 360,
    dir: -1,
    src: 'rec/ledger.jpg',
    rects: [
      {x: 316, y: 176, w: 882, h: 300},
      {x: 316, y: 480, w: 882, h: 300},
      {x: 316, y: 104, w: 882, h: 300},
      {x: 316, y: 330, w: 882, h: 300},
    ],
  },
  {
    loop: 270,
    dir: 1,
    src: 'rec/forge.jpg',
    rects: [
      {x: 330, y: 180, w: 880, h: 150},
      {x: 330, y: 350, w: 880, h: 150},
      {x: 330, y: 520, w: 880, h: 150},
      {x: 330, y: 690, w: 880, h: 150},
    ],
  },
  {
    loop: 420,
    dir: -1,
    src: 'rec/spawn.jpg',
    rects: [
      {x: 194, y: 340, w: 890, h: 170},
      {x: 194, y: 510, w: 890, h: 170},
      {x: 194, y: 205, w: 890, h: 110},
      {x: 194, y: 120, w: 890, h: 110},
    ],
  },
];

const Waterfall: React.FC<{f: number}> = ({f}) => {
  const push = interpolate(f, [0, 128], [1.0, 1.05], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <AbsoluteFill style={{background: N.bg, overflow: 'hidden'}}>
      <AbsoluteFill style={{perspective: 1000}}>
        <AbsoluteFill
          style={{
            transform: `rotateX(20deg) scale(${push})`,
            // AbsoluteFill is already a column flexbox, so `display: flex` alone
            // stacks the three columns on top of each other instead of beside
            // one another — the direction has to be stated
            display: 'flex',
            flexDirection: 'row',
            gap: 34,
            padding: '0 40px',
          }}
        >
          {COLS.map((col, ci) => {
            // Four copies, translated by exactly one copy — 25% — so the loop
            // is seamless AND the three copies that are not scrolling past
            // always cover the viewport. Two copies and a half-height travel
            // leaves a column-tall hole above or below the content, depending
            // on the direction, for most of the shot.
            const items = [...col.rects, ...col.rects, ...col.rects, ...col.rects];
            const p = (f % col.loop) / col.loop;
            const ty = col.dir === 1 ? -p * 25 : -25 + p * 25;
            return (
              <div key={ci} style={{flex: 1, overflow: 'hidden', position: 'relative'}}>
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    width: '100%',
                    transform: `translateY(${ty}%)`,
                  }}
                >
                  {items.map((r, k) => (
                    <div key={k} style={{marginBottom: 26}}>
                      <Slice
                        src={col.src}
                        rect={r}
                        w={560}
                        style={{
                          borderRadius: 12,
                          border: '1px solid #232D3B',
                          filter: 'brightness(1.35)',
                          boxShadow: '0 18px 40px rgba(0,0,0,0.5)',
                        }}
                      />
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </AbsoluteFill>
      </AbsoluteFill>

      {/* the edges of the wall are masked so rows do not enter and leave hard */}
      <AbsoluteFill
        style={{
          background:
            'linear-gradient(180deg, rgba(5,7,11,1) 0%, rgba(5,7,11,0) 200px, rgba(5,7,11,0) calc(100% - 200px), rgba(5,7,11,1) 100%)',
        }}
      />
      <Caption f={f} at={70} text="And it keeps going." />
    </AbsoluteFill>
  );
};

/* ================================================================== */
/* 6. runway-ground-skim                                               */

/**
 * `runway-ground-skim`. A downpour, not a tour: starts 1.5 frames apart, 9
 * frames of gravity each, so five or six cards are in the air at any moment —
 * "almost together, with a ripple". Landing is dead stop; the card records that
 * a 4.5% squash-and-rebound was rejected, because the whole feeling is
 * crispness. Then the page stands up from 66 degrees to face on, which is the
 * shot's full stop: the audience stops watching a performance and starts
 * looking at an interface.
 */
/** The set has no light; the plates are dark UI and need lifting to read. */
const SKIM_LIFT: React.CSSProperties = {filter: 'brightness(1.3)'};

const Skim: React.FC<{f: number}> = ({f}) => {
  const stand = ramp(f, 46, 58, Easing.bezier(0.3, 0, 0.2, 1));
  const rotX = 66 - stand * 66;
  const pull = interpolate(f, [46, 104], [1.16, 0.9], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.2, 1),
  });

  return (
    <AbsoluteFill style={{background: N.bg, overflow: 'hidden'}}>
      <AbsoluteFill style={{perspective: 1300, perspectiveOrigin: '50% 46%'}}>
        <AbsoluteFill
          style={{
            transformStyle: 'preserve-3d',
            transform: `scale(${pull}) rotateX(${rotX}deg)`,
          }}
        >
          <div
            style={{
              position: 'absolute',
              left: 300,
              top: 150,
              width: 1320,
              height: 780,
              transformStyle: 'preserve-3d',
            }}
          >
            {/* Drop heights are in surface pixels, and on a plane raked to 66
                degrees a translateZ of 700 puts the element clean out of frame.
                The first cut of this shot opened on half a second of black
                immediately after a flash cut — the downpour was happening above
                the top of the picture. Nothing here starts higher than 460. */}
            <div style={{position: 'absolute', left: 0, top: 0, transformStyle: 'preserve-3d'}}>
              <FloatWrap h={fall(f, 0, 10) * 400} maxH={460} axis="z">
                <Slice src="rec/ledger.jpg" rect={SIDEBAR} w={240} style={SKIM_LIFT} />
              </FloatWrap>
            </div>
            <div style={{position: 'absolute', left: 262, top: 10, transformStyle: 'preserve-3d'}}>
              <FloatWrap h={fall(f, 1.5, 10) * 370} maxH={460} axis="z">
                <Slice src="rec/ledger.jpg" rect={LEDGER_HEAD} w={1040} style={SKIM_LIFT} />
              </FloatWrap>
            </div>
            {LEDGER_CARDS.map((r, k) => {
              // 1.5f apart with a small deterministic jitter that never reorders
              const cue = 3 + k * 1.5 + (jit(k, 12) / 12) * 1.2;
              const h0 = 300 + ((k * 7919) % 150);
              return (
                <div
                  key={k}
                  style={{
                    position: 'absolute',
                    left: 262 + (k % 3) * 352,
                    top: 92 + Math.floor(k / 3) * 348,
                    transformStyle: 'preserve-3d',
                  }}
                >
                  <FloatWrap h={fall(f, cue, 9) * h0} maxH={460} axis="z">
                    <Slice
                      src="rec/ledger.jpg"
                      rect={r}
                      w={336}
                      style={{...SKIM_LIFT, borderRadius: 10, border: '1px solid #1D2530'}}
                    />
                  </FloatWrap>
                </div>
              );
            })}
          </div>
        </AbsoluteFill>
      </AbsoluteFill>

      {/* the press-down is held at ~32% so airborne cards stay visible */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(90% 80% at 50% 46%, rgba(0,0,0,0) 30%, rgba(0,0,0,0.32) 100%)`,
        }}
      />
      <Caption f={f} at={96} text="Every spawn you raised, on one page." />
    </AbsoluteFill>
  );
};

/* ================================================================== */
/* 7. neon-frame-orbit-drop                                            */

/**
 * `neon-frame-orbit-drop`. The frame is drawn, then the camera arcs from a
 * left-side view to a right-side one while every element in the page leaves,
 * falls and lands ON THE SAME FRAME.
 *
 * That simultaneity is the card's stated make-or-break, and an earlier version
 * with staggered landing was rejected in as many words: any stagger belongs to
 * the tour shots, and this one is a single arrival. The drop window is centred
 * on the rotation — rotating first and landing after reads as two separate
 * pieces of business.
 */
const OrbitDrop: React.FC<{f: number}> = ({f}) => {
  const W = 1240;
  const H = 846;
  const arc = ramp(f, 8, 96, Easing.bezier(0.35, 0, 0.3, 1));
  const rotY = 38 - arc * 64;
  const origin = 30 + arc * 34;

  // ONE landing moment for everything in the page.
  const LAND_START = 40;
  const LAND_DUR = 30;
  const h = fall(f, LAND_START, LAND_DUR) * 170;

  return (
    <AbsoluteFill style={{background: N.bg, overflow: 'hidden'}}>
      {[0, 1, 2].map((k) => (
        <div
          key={k}
          style={{
            position: 'absolute',
            left: 200 + k * 620,
            top: -160,
            width: 4,
            height: 1400,
            background: k === 1 ? N.neon : N.neon2,
            opacity: 0.13 * (1 - ramp(f, 112, 24)),
            filter: 'blur(4px)',
            transform: `rotate(${6 + k * 3}deg)`,
          }}
        />
      ))}

      <AbsoluteFill style={{perspective: 1500, perspectiveOrigin: `${origin}% 50%`}}>
        <div
          style={{
            position: 'absolute',
            left: 960 - W / 2,
            top: 540 - H / 2,
            width: W,
            height: H,
            transformStyle: 'preserve-3d',
            transform: `rotateY(${rotY}deg)`,
          }}
        >
          <NeonFrame f={f} start={0} w={W} h={H} dur={14} colour={N.neon2} />
          <div
            style={{
              position: 'absolute',
              inset: 10,
              overflow: 'hidden',
              background: '#080B10',
            }}
          >
            <div style={{position: 'absolute', left: 0, top: 20}}>
              <FloatWrap h={h}>
                <Slice src="rec/diag.jpg" rect={SIDEBAR} w={226} />
              </FloatWrap>
            </div>
            {/* Diagnostics, in three bands. The bands skip the run-scoped tiles
                in the middle of that page on purpose: on a machine with one run
                and no evals recorded they read "PASS RATE 0%", which is true and
                meaningless, and unreadably small numbers are exactly what a
                4-second orbit shot should not be arguing about. */}
            {[
              {top: 25, r: {x: 300, y: 100, w: 916, h: 160}}, // tabs, window, headline numbers
              {top: 254, r: {x: 300, y: 250, w: 916, h: 130}}, // latency histogram
              // stops at 805: below that the capture is the desktop, not the app
              {top: 451, r: {x: 300, y: 600, w: 916, h: 205}}, // usage · daily tokens · providers
            ].map((b) => (
              <div key={b.top} style={{position: 'absolute', left: 248, top: b.top}}>
                <FloatWrap h={h}>
                  <Slice src="rec/diag.jpg" rect={b.r} w={950} />
                </FloatWrap>
              </div>
            ))}
          </div>
        </div>
      </AbsoluteFill>

      <Caption f={f} at={72} text={SAFETY.local} />
    </AbsoluteFill>
  );
};

/* ================================================================== */

const Caption: React.FC<{f: number; at: number; text: string}> = ({f, at, text}) => {
  const o = ramp(f, at, 18);
  if (o <= 0.01) return null;
  return (
    <div
      style={{
        position: 'absolute',
        left: 96,
        bottom: 84,
        fontFamily: font.mono,
        fontSize: 27,
        letterSpacing: '0.04em',
        color: N.ink,
        opacity: o,
        transform: `translateY(${(1 - o) * 14}px)`,
        textShadow: '0 4px 24px rgba(0,0,0,0.9)',
      }}
    >
      <span style={{color: N.neon}}>▸ </span>
      {text}
    </div>
  );
};

const Cta: React.FC<{f: number}> = ({f}) => {
  const a = ramp(f, 2, 26, Easing.bezier(0.16, 1.2, 0.3, 1));
  const b = ramp(f, 22, 26, Easing.bezier(0.16, 1.2, 0.3, 1));
  return (
    <AbsoluteFill
      style={{
        background: N.bg,
        fontFamily: font.sans,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'column',
        textAlign: 'center',
      }}
    >
      <div
        style={{
          position: 'absolute',
          width: 900,
          height: 900,
          borderRadius: '50%',
          background: `radial-gradient(circle, ${N.neon}22 0%, rgba(0,0,0,0) 66%)`,
          filter: 'blur(60px)',
          opacity: a,
        }}
      />
      <div
        style={{
          fontSize: 132,
          fontWeight: 720,
          letterSpacing: '-0.05em',
          color: N.ink,
          opacity: a,
          transform: `translateY(${(1 - a) * 26}px)`,
        }}
      >
        {PRODUCT.name}
      </div>
      <div style={{marginTop: 14, fontSize: 30, color: N.dim, opacity: a}}>
        {PRODUCT.tagline}
      </div>
      <div
        style={{
          marginTop: 48,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 16,
          padding: '24px 48px',
          borderRadius: 999,
          background: N.neon,
          color: '#160A02',
          fontSize: 31,
          fontWeight: 680,
          opacity: b,
          transform: `translateY(${(1 - b) * 18}px)`,
          boxShadow: `0 22px 60px ${N.neon}44`,
        }}
      >
        <span>↓</span> Download for macOS
      </div>
      <div
        style={{
          marginTop: 20,
          fontFamily: font.mono,
          fontSize: 20,
          letterSpacing: '0.1em',
          color: N.faint,
          opacity: b,
        }}
      >
        {PRODUCT.platform} · {PRODUCT.license} · {PRODUCT.status}
      </div>
    </AbsoluteFill>
  );
};

/* ================================================================== */

const BEATS = [
  {at: 0, C: Spotlight},
  {at: 165, C: Forerun},
  {at: 300, C: Graze},
  {at: 445, C: Glide},
  {at: 590, C: Waterfall},
  {at: 720, C: Skim},
  {at: 865, C: OrbitDrop},
  {at: 985, C: Cta},
];

/**
 * `shot-transitions` A — flash-cut. A white flash five frames either side of the
 * cut, and only on the seams where two shots of comparable energy meet. The
 * card is explicit that the flash covers a hard cut and is not a decorative
 * light effect, so the slower seams are left as plain cuts.
 */
const FLASH_AT = [300, 445, 720];

export const Runway: React.FC = () => {
  const f = useCurrentFrame();
  let i = 0;
  for (let k = 0; k < BEATS.length; k++) if (f >= BEATS[k].at) i = k;
  const {at, C} = BEATS[i];

  let flash = 0;
  for (const c of FLASH_AT) {
    if (f >= c - 5 && f <= c + 5) flash = Math.max(flash, 1 - Math.abs(f - c) / 5);
  }

  return (
    <AbsoluteFill style={{background: N.bg}}>
      <C f={f - at} />
      {flash > 0 ? (
        <AbsoluteFill style={{background: '#fff', opacity: flash * 0.85}} />
      ) : null}
    </AbsoluteFill>
  );
};
