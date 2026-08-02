import React from 'react';
import {
  AbsoluteFill,
  Easing,
  Freeze,
  interpolate,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {Mark} from '../components/Mark';
import {PRODUCT} from '../facts';
import {CHARACTER, CHARACTER_OPEN} from '../lightTheme';
import {font} from '../theme';
import {
  Forerun,
  Glide,
  Graze,
  N,
  OrbitDrop,
  Skim,
  Spotlight,
  Waterfall,
} from './Runway';

/**
 * FILM 7 — "ORIGIN". The Runway shot list at sixty seconds, opening and closing
 * on the brand character.
 *
 * F6 is thirty-six seconds of interface with no way in and no way out: it cuts
 * up on a spotlight and cuts off on a download. That is the right shape for a
 * feed and the wrong shape for a minute — a minute wants somebody to meet.
 *
 * THE HINGE. The amber emblem glowing on the cat's chest is the same idea as
 * the Arslan mark — one lit node with arms radiating out to more nodes — so the
 * film pushes into the chest until the emblem fills the frame, hands the figure
 * over to the vector mark at that exact position and size, and lets the mark's
 * legs fan out. The product's own line for that figure is "One Becomes Many",
 * and the shot straight after it is the page where you raise the many.
 *
 * They are NOT the same drawing, and this film does not pretend otherwise. The
 * emblem is a four-armed cross; `web/public/favicon.svg` is one host node with
 * three legs down to three spawns. So the swap is timed to the peak of the
 * push, where the plate is at 4.5px of blur and 40% opacity and the emblem is a
 * soft glare rather than a readable shape — a hand-off the eye reads as
 * continuous, instead of a morph claimed between two figures that do not match.
 * An earlier cut in this repo called them "literally the same drawing". They
 * are not, and counting the arms takes five seconds.
 *
 * The emblem's centre — (0.477, 0.582) normalised, span 98/1280 — was measured
 * once, from the centroid of saturated-amber pixels in the lower-centre box of
 * the clip's settled final frame, and lives in `lightTheme.ts`. Both character
 * assets are cuts of the same source ending on the same frame, so the number
 * holds for either. It is imported rather than restated here: a hand-off that
 * is out by twenty pixels reads as a dissolve instead of a morph, and the one
 * way to guarantee that is to never type the number twice.
 *
 * SHOT ORDER CHANGES, and for the better. F6 runs spotlight → forerun; here the
 * mark hands off INTO the neon frame, so the forerun has to be first. That puts
 * the two neon frames at positions one and eight — the maximum separation the
 * cards ask for, against F6's two and seven — and it fixes the story order as
 * well: raise one (the empty CREATE dialog), then look at what you raised (the
 * spotlight on a finished card), then equip it, and so on. Cause before effect.
 *
 * The character clip is GENERATED BRAND IMAGERY, not a screen recording of the
 * product, and it is captioned as such on screen for as long as it is on screen.
 * Everything between the two character beats is the shipped client.
 */

export const ORIGIN_FRAMES = 1800; // 60s at 30fps

const glide = Easing.bezier(0.4, 0, 0.2, 1);

const ramp = (f: number, s: number, l: number, e = glide) =>
  interpolate(f, [s, s + l], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: e,
  });

/* ================================================================== */
/* The character plate, and where the emblem lands on it               */

/**
 * 1620 wide against 1280 of source is a 1.27x upscale — mild, and the shot is
 * a slow push on a soft-lit subject where it does not show. Full bleed would be
 * 1.5x and it does show. The remaining ground on all four sides is the film's
 * own black, so the clip reads as a lit plate in F6's world rather than as a
 * different film spliced onto the front.
 */
const CARD = {w: 1620, h: (720 / 1280) * 1620};
CARD.h = Math.round(CARD.h);
const CARD_X = (1920 - CARD.w) / 2;
const CARD_Y = (1080 - CARD.h) / 2;

const EMBLEM = {
  x: CARD_X + CHARACTER.emblem.x * CARD.w,
  y: CARD_Y + CHARACTER.emblem.y * CARD.h,
  size: CHARACTER.emblem.size * CARD.w,
};

/**
 * The mark's figure fills only the middle ~59% of its 32-unit viewBox, so a box
 * sized to the emblem's span would draw a mark visibly smaller than the glow it
 * replaces and the hand-off would read as a shrink.
 */
const MARK_BOX = 1 / 0.594;

/** Faint angled tubes — the same furniture the neon-frame shots stand in. */
const Tubes: React.FC<{f: number; fade: number}> = ({f, fade}) => (
  <>
    {[0, 1, 2, 3].map((k) => (
      <div
        key={k}
        style={{
          position: 'absolute',
          left: 90 + k * 470,
          top: -120,
          width: 3,
          height: 1320,
          background: k % 2 ? N.neon2 : N.violet,
          opacity: 0.14 * ramp(f, 4 + k * 3, 20) * fade,
          filter: 'blur(3px)',
          transform: `rotate(${8 + k * 2}deg)`,
        }}
      />
    ))}
  </>
);

/** Small, permanent, and true for as long as the character is on screen. */
const Provenance: React.FC<{o: number}> = ({o}) =>
  o <= 0.01 ? null : (
    <div
      style={{
        position: 'absolute',
        right: 64,
        bottom: 56,
        fontFamily: font.mono,
        fontSize: 15,
        letterSpacing: '0.1em',
        color: 'rgba(233,238,246,0.34)',
        opacity: o,
      }}
    >
      BRAND CHARACTER · GENERATED IMAGERY
    </div>
  );

/* ================================================================== */
/* 1. The creature, and the push into the mark                         */

const OPEN_LEN = 365;
const PUSH_START = 196;
const PUSH_END = 300;
const HANDOFF = 286;
const PUSH_SCALE = 3.4;

const Creature: React.FC<{f: number}> = ({f}) => {
  const enter = ramp(f, 0, 34);

  const push = ramp(f, PUSH_START, PUSH_END - PUSH_START);
  const scale = 1 + (PUSH_SCALE - 1) * push;

  // Focus falls away as the real pixels run out, so the softness at the end of
  // the push reads as a rack focus rather than as an upscale.
  const blur = interpolate(f, [PUSH_START + 52, PUSH_END], [0, 4.5], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // The plate goes out under the mark rather than cutting — by the time the
  // vector is at full strength there is nothing behind it but the set.
  const handoff = ramp(f, HANDOFF, 30);

  const word = interpolate(f, [46, 78, 168, 192], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: glide,
  });

  return (
    <AbsoluteFill style={{background: N.bg, overflow: 'hidden'}}>
      <Tubes f={f} fade={enter * (1 - handoff * 0.4)} />

      <AbsoluteFill
        style={{
          opacity: enter * (1 - handoff),
          transform: `scale(${scale})`,
          transformOrigin: `${EMBLEM.x}px ${EMBLEM.y}px`,
          filter: blur > 0.05 ? `blur(${blur}px)` : undefined,
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: CARD_X,
            top: CARD_Y,
            width: CARD.w,
            height: CARD.h,
            overflow: 'hidden',
            borderRadius: 6,
            border: `1px solid ${N.neon}33`,
            boxShadow: `0 0 120px ${N.neon}14`,
            transform: `scale(${0.99 + enter * 0.01})`,
          }}
        >
          {/* Hold on the settled pose once the clip runs out, rather than
              cutting away from it mid-push. */}
          <Freeze frame={Math.min(f, CHARACTER_OPEN.frames - 1)}>
            <OffthreadVideo
              src={staticFile(CHARACTER_OPEN.src)}
              muted
              style={{width: '100%', height: '100%', objectFit: 'cover'}}
            />
          </Freeze>
          {/* Cooled a little so a warm, bright clip and a near-black set read
              as one exposure rather than two films spliced together. */}
          <AbsoluteFill
            style={{background: 'linear-gradient(180deg, #0A1220 0%, #06131A 100%)', opacity: 0.2}}
          />
        </div>
      </AbsoluteFill>

      {/* Ground the plate: everything outside the emblem falls away as we push */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(${1200 - push * 780}px ${900 - push * 620}px at ${EMBLEM.x}px ${EMBLEM.y}px, rgba(0,0,0,0) 30%, rgba(3,5,9,${0.55 + push * 0.45}) 100%)`,
        }}
      />

      <div
        style={{
          position: 'absolute',
          left: 96,
          bottom: 92,
          fontFamily: font.sans,
          opacity: word,
          transform: `translateY(${(1 - word) * 14}px)`,
        }}
      >
        <div style={{fontSize: 66, fontWeight: 700, letterSpacing: '-0.04em', color: N.ink}}>
          {PRODUCT.name}
        </div>
        <div
          style={{
            marginTop: 8,
            fontFamily: font.mono,
            fontSize: 20,
            letterSpacing: '0.16em',
            color: N.neon,
          }}
        >
          {PRODUCT.tagline.toUpperCase()}
        </div>
      </div>

      <Provenance o={enter * (1 - ramp(f, HANDOFF - 20, 26))} />
    </AbsoluteFill>
  );
};

/**
 * The mark, drawn by the FILM rather than by either shot, so it can outlive the
 * cut at OPEN_LEN. It appears at the emblem's exact place and size at the end of
 * the push, settles to the centre, and is still on screen — fading — while the
 * forerun's neon frame runs out around it. One node becoming many, and then the
 * page where you make one.
 */
const HingeMark: React.FC<{f: number}> = ({f}) => {
  const on = ramp(f, HANDOFF, 24);
  const out = ramp(f, OPEN_LEN + 8, 34);
  const o = on * (1 - out);
  if (o <= 0.01) return null;

  const push = ramp(f, PUSH_START, PUSH_END - PUSH_START);
  const scale = 1 + (PUSH_SCALE - 1) * push;
  const settle = ramp(f, HANDOFF + 14, 92);

  const size = EMBLEM.size * scale * MARK_BOX;
  const x = EMBLEM.x + (960 - EMBLEM.x) * settle;
  const y = EMBLEM.y + (540 - EMBLEM.y) * settle;

  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      <div
        style={{
          position: 'absolute',
          left: x - size / 2,
          top: y - size / 2,
          opacity: o,
        }}
      >
        <Mark frame={f - HANDOFF} size={size} live tone={N.neon} />
      </div>
    </AbsoluteFill>
  );
};

/* ================================================================== */
/* 3. The close — the character comes back, and the download arrives   */

const CLOSE_AT = 1480;

/**
 * The cat returns at 0.59x of source — sharper than it has been all film — and
 * sits on the left while the call to action builds on the right. It plays the
 * tail of the clip, where the circuit wall behind it lights up, and then holds.
 *
 * The film opened on the character alone and closes on the character beside the
 * download, which is the same move the approved cinematic cut makes: pull back
 * until there is room for the words, rather than cutting to a title card.
 */
const CAT_W = 760;
const CAT_H = Math.round((720 / 1280) * CAT_W);

const Close: React.FC<{f: number}> = ({f}) => {
  const catIn = ramp(f, 16, 40);
  // play the tail 1:1 from frame 100, then settle
  const vf = Math.min(CHARACTER_OPEN.frames - 1, 100 + Math.max(0, f - 20));

  const head = ramp(f, 78, 34);
  const sub = ramp(f, 96, 34);
  const btn = ramp(f, 132, 34);
  const meta = ramp(f, 160, 30);

  return (
    <AbsoluteFill style={{background: N.bg, overflow: 'hidden'}}>
      <Tubes f={f} fade={0.8} />

      <div
        style={{
          position: 'absolute',
          left: 128,
          top: 540 - CAT_H / 2,
          width: CAT_W,
          height: CAT_H,
          overflow: 'hidden',
          borderRadius: 6,
          border: `1px solid ${N.neon}33`,
          boxShadow: `0 0 110px ${N.neon}14`,
          opacity: catIn,
          transform: `translateY(${(1 - catIn) * 18}px)`,
        }}
      >
        <Freeze frame={vf}>
          <OffthreadVideo
            src={staticFile(CHARACTER_OPEN.src)}
            muted
            style={{width: '100%', height: '100%', objectFit: 'cover'}}
          />
        </Freeze>
        <AbsoluteFill
          style={{background: 'linear-gradient(180deg, #0A1220 0%, #06131A 100%)', opacity: 0.2}}
        />
      </div>

      <div style={{position: 'absolute', left: 1016, top: 300, width: 840, fontFamily: font.sans}}>
        <div
          style={{
            fontSize: 104,
            fontWeight: 720,
            letterSpacing: '-0.05em',
            color: N.ink,
            lineHeight: 1,
            opacity: head,
            transform: `translateY(${(1 - head) * 22}px)`,
          }}
        >
          {PRODUCT.name}
        </div>
        <div
          style={{
            marginTop: 16,
            fontSize: 27,
            color: N.dim,
            opacity: sub,
            transform: `translateY(${(1 - sub) * 16}px)`,
          }}
        >
          {PRODUCT.tagline}
        </div>
        <div
          style={{
            marginTop: 46,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 15,
            padding: '22px 44px',
            borderRadius: 999,
            background: N.neon,
            color: '#160A02',
            fontSize: 29,
            fontWeight: 680,
            opacity: btn,
            transform: `translateY(${(1 - btn) * 16}px)`,
            boxShadow: `0 22px 60px ${N.neon}44`,
          }}
        >
          <span>↓</span> Download for macOS
        </div>
        <div
          style={{
            marginTop: 22,
            fontFamily: font.mono,
            fontSize: 16,
            letterSpacing: '0.06em',
            whiteSpace: 'nowrap',
            color: N.faint,
            opacity: meta,
          }}
        >
          {PRODUCT.platform} · {PRODUCT.license} · {PRODUCT.status}
        </div>
      </div>

      <Provenance o={catIn * 0.9} />
    </AbsoluteFill>
  );
};

/* ================================================================== */

/**
 * Durations are longer than F6's almost everywhere, because a minute is not
 * thirty-six seconds with more shots in it — it is the same shots with room to
 * land. The two that are NOT longer are the glide and the waterfall: the glide's
 * strip runs out at 138 frames and holding past that is a stall, and the
 * waterfall is an atmosphere shot that starts reading as padding the moment it
 * outstays its point.
 */
const BEATS = [
  {at: 0, C: Creature},
  {at: OPEN_LEN, C: Forerun}, // 365 · 170 — raise one
  {at: 535, C: Spotlight}, // 185 — look at what you raised
  {at: 720, C: Graze}, // 155 — equip it
  {at: 875, C: Glide}, // 145 — all of it, local
  {at: 1020, C: Waterfall}, // 150 — and it keeps going
  {at: 1170, C: Skim}, // 160 — every spawn on one page
  {at: 1330, C: OrbitDrop}, // 150 — off by default
  {at: CLOSE_AT, C: Close}, // 320
];

/**
 * `shot-transitions` A — flash-cut, five frames either side, only where two
 * shots of comparable energy meet. The seam out of the creature is deliberately
 * not one of them: that cut is a morph through the mark, and a flash over it
 * would hide the single thing the opening exists to show.
 */
const FLASH_AT = [720, 875, 1170];

export const Origin: React.FC = () => {
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
      {/* drawn by the film, not by a shot, so it survives the cut at OPEN_LEN */}
      <HingeMark f={f} />
      {flash > 0 ? <AbsoluteFill style={{background: '#fff', opacity: flash * 0.85}} /> : null}
    </AbsoluteFill>
  );
};
