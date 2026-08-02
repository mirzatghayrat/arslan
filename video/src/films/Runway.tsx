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
 * ON THE FOOTAGE. Every frame is the real client — nothing here is drawn UI.
 *
 * The film was first cut from a 480p screen recording, upscaled to 1280x872,
 * which held to about 1.7x and set the ceiling on every shot in it. It is now
 * cut from Retina window screenshots at 2560x1680, and the difference is not
 * only that the type is sharp: it changed what the shots are allowed to do.
 * `spotlight-hero-card` asks for a 2.6x push onto one card. A ledger card was
 * 276 pixels wide in the old plate, so the push stopped at 1.6x and even that
 * was a 2.2x upscale; the card is 603 pixels now, the page sits at 0.59x, and
 * the move the card actually specifies lands at about 1.45x of native — the
 * bigger push AND the sharper frame, which is not a trade that was available
 * before.
 *
 * The screenshots also brought seven pages the recording never visited, and
 * two of them changed what the film says rather than how it looks. The forerun
 * used to assemble the ledger — six spawns already built — under a caption
 * about raising your own; it now assembles the empty CREATE dialog, which is
 * the act instead of the result. The close used to be Diagnostics, whose tiles
 * read "PASS RATE 0%" on a machine with one run; it is now the Automation page,
 * where every switch that can spend money or write to memory is off and the
 * product says so in its own words, under a caption about local-first. Better
 * material did not just raise the resolution — it retired two compromises.
 */

export const N = {
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

/**
 * Plate dimensions, per plate.
 *
 * These are macOS window screenshots at Retina scale — 2560x1680 native — not
 * frames lifted from a screen recording, which is what this film was first cut
 * from. `ledger` is the only one kept at full size, because the opening pushes
 * onto a single card and that is the one place in the film where the extra
 * pixels get spent. The rest are at 1920, still above 1:1 for every use.
 *
 * They carry a light desktop in the window's own rounded corners, so anything
 * showing a whole page has to clip its own radius or four pale wedges appear on
 * a black set.
 */
const PLATES: Record<string, {w: number; h: number}> = {
  'rec/ledger.jpg': {w: 2560, h: 1680},
  'rec/create.jpg': {w: 1920, h: 1260},
  'rec/equip.jpg': {w: 1920, h: 1260},
  'rec/home.jpg': {w: 1920, h: 1260},
  'rec/chat.jpg': {w: 1920, h: 1260},
  'rec/skills.jpg': {w: 1920, h: 1260},
  'rec/tools.jpg': {w: 1920, h: 1260},
  'rec/mcp.jpg': {w: 1920, h: 1260},
  'rec/forge.jpg': {w: 1920, h: 1260},
  'rec/diag.jpg': {w: 1920, h: 1260},
  'rec/brain.jpg': {w: 1920, h: 1260},
  'rec/auto.jpg': {w: 1920, h: 1260},
};

/** Clips the window's own rounded corners off a full-page plate. */
const PAGE_RADIUS = 16;

/**
 * A rectangle of a plate, in that plate's pixel coordinates, drawn at `w` wide.
 *
 * Slicing rather than showing whole pages is what makes the drop shots possible
 * at all: a screenshot is one flat image, so "components falling from above"
 * has to be regions of that image moving independently. It is also what the
 * waterfall card asks for directly — card-level blocks, because whole-page
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
  const p = PLATES[src];
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
        backgroundSize: `${p.w * k}px ${p.h * k}px`,
        backgroundPosition: `${-rect.x * k}px ${-rect.y * k}px`,
      }}
    />
  );
};

/** A whole page, with the window's own corners clipped off. */
const Page: React.FC<{src: string; w: number; style?: React.CSSProperties}> = ({src, w, style}) => {
  const p = PLATES[src];
  return (
    <Img
      src={staticFile(src)}
      style={{
        width: w,
        height: (p.h / p.w) * w,
        display: 'block',
        borderRadius: PAGE_RADIUS,
        ...style,
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
/* Slice tables. LEDGER_* are in the 2560 plate; everything else 1920.  */

const LEDGER_CARDS: Rect[] = [
  {x: 577, y: 338, w: 603, h: 603},
  {x: 1233, y: 338, w: 603, h: 603},
  {x: 1889, y: 338, w: 603, h: 603},
  {x: 577, y: 995, w: 603, h: 603},
  {x: 1233, y: 995, w: 603, h: 603},
  {x: 1889, y: 995, w: 603, h: 603},
];
/** Title, count pill, subtitle and the SYNTHESIZE SPAWN button, in one band. */
const LEDGER_HEAD: Rect = {x: 577, y: 176, w: 1918, h: 124};
const SIDEBAR: Rect = {x: 8, y: 8, w: 500, h: 1664};

/**
 * Tiles for the ground shot, all at 2:1.
 *
 * The first version cut these along one dialog's own regions — a header band, a
 * scope band, three columns — and every one came out a different shape. Laid on
 * a plane raked past fifty degrees, a 66-pixel band foreshortens to a bright
 * line: six tiles went past the camera and not one read as an interface.
 * Everything on the runway is now the same aspect, so the rake affects all of
 * them equally and the eye has something constant to measure the travel against.
 *
 * All six now come from *different* pages, which is the other half of the fix:
 * six crops of one dialog is one tile shown six times, however well it moves.
 * They are the four Capability tabs plus the two dialogs, because the caption on
 * this shot is `SPAWNS.equip` and these are the pages that show it.
 */
const TILES: {src: string; rect: Rect}[] = [
  {src: 'rec/tools.jpg', rect: {x: 440, y: 300, w: 1420, h: 710}}, // tools, wired and not
  {src: 'rec/skills.jpg', rect: {x: 440, y: 600, w: 1420, h: 710}}, // skill packs, row after row
  {src: 'rec/mcp.jpg', rect: {x: 440, y: 330, w: 1420, h: 710}}, // MCP servers, one-click
  {src: 'rec/equip.jpg', rect: {x: 226, y: 500, w: 1470, h: 735}}, // SKILLS · TOOLS · MCPS, ticked
  {src: 'rec/forge.jpg', rect: {x: 440, y: 195, w: 1420, h: 710}}, // forge your own
  {src: 'rec/create.jpg', rect: {x: 226, y: 540, w: 1470, h: 735}}, // seeds · skills · tools
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
const LEDGER_SRC = PLATES['rec/ledger.jpg'];
const PAGE_K = 1520 / LEDGER_SRC.w;
const PAGE_L = 960 - (LEDGER_SRC.w * PAGE_K) / 2;
const PAGE_T = 540 - (LEDGER_SRC.h * PAGE_K) / 2;
const HERO = LEDGER_CARDS[0];
const HERO_BOX = {
  left: PAGE_L + HERO.x * PAGE_K,
  top: PAGE_T + HERO.y * PAGE_K,
  w: HERO.w * PAGE_K,
  h: HERO.h * PAGE_K,
};
const HERO_CX = HERO_BOX.left + HERO_BOX.w / 2;
const HERO_CY = HERO_BOX.top + HERO_BOX.h / 2;

/* The card is the first of six, so it sits high and left on the page. Scaling
   about its own centre keeps it exactly there, and at the full push that runs it
   off the top of the frame — so the stage slides by this much as the camera
   moves in, and the card ends up composed rather than merely enlarged. */
const HERO_TO = {x: 900, y: 575};
const HERO_DX = HERO_TO.x - HERO_CX;
const HERO_DY = HERO_TO.y - HERO_CY;

/* The lift happens inside the scaled layer, so on screen it is this times the
   zoom — 44 at 2.42x is already a 106-pixel rise. The first pass kept the 96
   that suited a 1.6x push and floated the card's head clean out of frame. */
const LIFT_PX = 44;

const STOPS = [
  {x: 1480, y: 300, r: 460},
  {x: 1180, y: 820, r: 500},
  {x: 620, y: 760, r: 380},
  // at lock the pool is the pushed card plus a margin, and no more: a pool wide
  // enough to catch the neighbouring cards is not a spotlight, it is a lamp
  {x: HERO_CX, y: HERO_CY, r: 330},
];

export const Spotlight: React.FC<{f: number}> = ({f}) => {
  const leg = interpolate(f, [6, 20, 34, 48], [0, 1, 2, 3], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const i = Math.min(STOPS.length - 1, Math.floor(leg));
  const j = Math.min(STOPS.length - 1, i + 1);
  const t = leg - i;

  // Camera: static wide, then the push onto the card and a three-quarter.
  //
  // 0.94 → 2.42 is the 2.6x the shot card actually asks for, which the film
  // could not afford when it was cut from a 480p recording — the push stopped
  // at 1.62 and even that was a 2.2x upscale. Off a 2560 Retina plate the page
  // sits at 0.59x, so the card lands at about 1.45x of native: the move is the
  // one the card specifies AND it is sharper than the compromise was.
  const zoom = interpolate(f, [0, 32, 60], [0.94, 0.94, 2.42], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.2, 1),
  });
  const rotY = interpolate(f, [32, 60], [0, 22], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.2, 1),
  });
  // the reframing rides the same curve as the push, so it is one camera move
  const dolly = interpolate(f, [32, 60], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.2, 1),
  });
  const tx = HERO_DX * dolly;
  const ty = HERO_DY * dolly;

  // the pool travels with the stage once the camera starts moving, or the light
  // stays where the card used to be
  const px = STOPS[i].x + (STOPS[j].x - STOPS[i].x) * t + tx;
  const py = STOPS[i].y + (STOPS[j].y - STOPS[i].y) * t + ty;
  const lockPulse = ramp(f, 48, 3) * (1 - ramp(f, 51, 9));
  // the pool opens up as the camera pushes, so the card does not outgrow it
  const grow = ramp(f, 34, 46);
  const pr = (STOPS[i].r + (STOPS[j].r - STOPS[i].r) * t) * (1 + lockPulse * 0.08 + grow * 0.6);

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
          transform: `translate(${tx}px, ${ty}px) scale(${zoom}) rotateY(${rotY}deg)`,
          transformOrigin: `${(HERO_CX / 1920) * 100}% ${(HERO_CY / 1080) * 100}%`,
        }}
      >
        {/* the page the card belongs to */}
        <Page
          src="rec/ledger.jpg"
          w={LEDGER_SRC.w * PAGE_K}
          style={{position: 'absolute', left: PAGE_L, top: PAGE_T}}
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
            transform: `translateY(${-lift * LIFT_PX + bob}px) scale(${press})`,
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
      <AbsoluteFill style={{filter: 'brightness(0.16) saturate(0.72)'}}>{stage}</AbsoluteFill>
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
export const Forerun: React.FC<{f: number}> = ({f}) => {
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
            {/* An empty spawn, being raised. Title first, then the mission
                field, then the three columns you equip it from — starts
                staggered, falls overlapping.

                This shot used to assemble the ledger, which was the roster
                already built. Saying "a roster you raise" over six finished
                cards is showing the result and claiming the act; the blank
                CREATE dialog — no name, no domain, an empty mission box and a
                seed library to draft from — is the act itself, and it is the
                one page in the product that proves the film's central claim
                instead of asserting it. */}
            {CREATE_PARTS.map((c, k) => (
              <div key={k} style={{position: 'absolute', left: c.left, top: c.top}}>
                <FloatWrap h={fall(f, 30 + k * 6, 24) * 145}>
                  <Slice src="rec/create.jpg" rect={c.rect} w={c.w} />
                </FloatWrap>
              </div>
            ))}
          </div>
        </div>
      </AbsoluteFill>

      <Caption f={f} at={88} text="Not a roster that ships. One you raise." />
    </AbsoluteFill>
  );
};

/**
 * The CREATE dialog, taken apart along its own seams and laid back out at
 * k = 0.74 inside the neon frame's 1160x784 interior. Positions are the
 * dialog's real geometry scaled, not a new arrangement — the point of the shot
 * is that the thing assembling is a page from the product, so if the pieces
 * land somewhere the page never puts them, the shot is a collage instead.
 */
const CREATE_K = 0.74;
const CREATE_ORIGIN = {x: 194, y: 104};
const CREATE_PARTS = (
  [
    {x: 194, y: 104, w: 1529, h: 118}, // Untitled spawn · CREATE
    {x: 226, y: 262, w: 1465, h: 126}, // SCOPE / MISSION — an empty box
    {x: 226, y: 405, w: 1465, h: 62}, // Name · Domain · RECOMMEND
    {x: 226, y: 477, w: 1465, h: 55}, // Role / persona
    {x: 226, y: 553, w: 360, h: 190}, // SEEDS — the persona library to draft from
    {x: 598, y: 553, w: 352, h: 475}, // SKILLS
    {x: 970, y: 553, w: 352, h: 475}, // TOOLS
    {x: 1344, y: 553, w: 346, h: 81}, // MCPS
    {x: 1470, y: 1080, w: 240, h: 62}, // CANCEL · CREATE
  ] as Rect[]
).map((rect) => ({
  rect,
  w: rect.w * CREATE_K,
  left: 14 + (rect.x - CREATE_ORIGIN.x) * CREATE_K,
  top: 8 + (rect.y - CREATE_ORIGIN.y) * CREATE_K,
}));

/* ================================================================== */
/* 3. graze-face-tour                                                  */

/**
 * `graze-face-tour`. The camera flies low along the page as if it were terrain,
 * at an angle steep enough that the sidebar and the rows become landscape.
 * Depth of field is part of the grammar rather than decoration — everything
 * sharp reads as a flat scroll.
 */
export const Graze: React.FC<{f: number}> = ({f}) => {
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
                        // A nudge, not a lift. The 480p plates this film was
                        // first cut from were dark enough to need 1.4x; the
                        // Retina screenshots are already exposed, and the same
                        // number blows the amber chips out to flat yellow.
                        filter: 'brightness(1.12)',
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
// Four dense pages, and four different ones — ask, memory, the live thread with
// its diagnostics rail, and the numbers. The Capability Library's landing state
// is mostly empty set; an empty page sliding past at this angle is a dead
// second, and the tabs behind it already carry the graze.
const GLIDE_PAGES = ['rec/home.jpg', 'rec/brain.jpg', 'rec/chat.jpg', 'rec/diag.jpg'];
const GLIDE_W = 1180;
const GLIDE_H = (1260 / 1920) * GLIDE_W;
const GLIDE_GAP = 90;
const GLIDE_STEP = GLIDE_W + GLIDE_GAP;

export const Glide: React.FC<{f: number}> = ({f}) => {
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
          <Page src={p} w={GLIDE_W} />
          <div
            style={{
              position: 'absolute',
              inset: 0,
              borderRadius: PAGE_RADIUS,
              border: `1px solid ${k % 2 ? N.neon2 : N.neon}55`,
            }}
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
  // Every column crops at roughly the same fraction of its plate's width, so
  // all three land at the same zoom on the wall. A single ledger card is 603
  // pixels of a 2560 plate; shown in a 560-wide column beside two crops taken
  // 1420 wide off a 1920 plate, it is twice their scale and the wall stops
  // reading as one surface.
  {
    loop: 360,
    dir: -1,
    src: 'rec/ledger.jpg',
    rects: [
      {x: 577, y: 320, w: 1918, h: 640},
      {x: 577, y: 980, w: 1918, h: 640},
      {x: 577, y: 170, w: 1918, h: 640},
      {x: 577, y: 650, w: 1918, h: 640},
    ],
  },
  {
    loop: 270,
    dir: 1,
    src: 'rec/skills.jpg',
    rects: [
      {x: 440, y: 610, w: 1420, h: 474},
      {x: 440, y: 1080, w: 1420, h: 474},
      {x: 440, y: 195, w: 1420, h: 474},
      {x: 440, y: 845, w: 1420, h: 474},
    ],
  },
  {
    loop: 420,
    dir: -1,
    src: 'rec/mcp.jpg',
    rects: [
      {x: 440, y: 336, w: 1420, h: 474},
      {x: 440, y: 770, w: 1420, h: 474},
      {x: 440, y: 195, w: 1420, h: 474},
      {x: 440, y: 1000, w: 1420, h: 474},
    ],
  },
];

export const Waterfall: React.FC<{f: number}> = ({f}) => {
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
                          filter: 'brightness(1.1)',
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
/** A nudge to separate the cards from the set — see the graze on the number. */
const SKIM_LIFT: React.CSSProperties = {filter: 'brightness(1.1)'};

export const Skim: React.FC<{f: number}> = ({f}) => {
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
 * The Automation page, in four pieces, at ONE scale.
 *
 * Every piece is placed by scaling its real position on the page, exactly as
 * the CREATE dialog is in the forerun. The first version sized each block by
 * eye instead, and one of them — a 348-wide crop asked to render 380 wide —
 * came out 743 pixels tall inside an 826-pixel frame, landed on top of its
 * neighbour and pushed a third outside the neon frame entirely. Deriving the
 * layout makes that class of mistake impossible to write.
 *
 * The crop is the page's content band rather than the whole page: below the
 * automation panel the real page is empty, and reproducing 300 pixels of
 * faithful nothing in a four-second shot is not honesty, it is a dead corner.
 */
const AUTO_BAND = {x: 0, y: 96, w: 1900, h: 829}; // the part of the page with things on it
const AUTO_K = 1220 / AUTO_BAND.w;
const AUTO_TOP = (826 - AUTO_BAND.h * AUTO_K) / 2; // centred in the frame's interior
const AUTO_PARTS = (
  [
    {x: 8, y: 140, w: 392, h: 785}, // the nav, all the way down to System Settings
    {x: 410, y: 100, w: 1480, h: 128}, // Settings · what it remembers and what runs on its own
    {x: 424, y: 240, w: 366, h: 690}, // the settings nav, Automation selected
    {x: 800, y: 240, w: 1092, h: 680}, // AUTOMATION — every switch off, and it says so
  ] as Rect[]
).map((rect) => ({
  rect,
  w: rect.w * AUTO_K,
  left: (rect.x - AUTO_BAND.x) * AUTO_K,
  top: AUTO_TOP + (rect.y - AUTO_BAND.y) * AUTO_K,
}));

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
export const OrbitDrop: React.FC<{f: number}> = ({f}) => {
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
            {/* The Automation page, arriving all at once.

                This shot closed on Diagnostics until the screenshots arrived,
                and Diagnostics was always a compromise: on a machine with one
                run and no evals recorded, its tiles read "PASS RATE 0%" — true,
                meaningless, and not what you want a viewer squinting at over
                the last line of the film. Automation says the thing the caption
                claims instead of sitting next to it. Everything that can spend
                money or write to memory is on this page, every switch is off,
                and the page says so in the product's own words. */}
            {AUTO_PARTS.map((b, k) => (
              <div key={k} style={{position: 'absolute', left: b.left, top: b.top}}>
                <FloatWrap h={h}>
                  <Slice src="rec/auto.jpg" rect={b.rect} w={b.w} />
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

export const Caption: React.FC<{f: number; at: number; text: string}> = ({f, at, text}) => {
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

export const Cta: React.FC<{f: number}> = ({f}) => {
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
