import React from 'react';
import {AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {Mark} from '../components/Mark';
import {PRODUCT, SPAWNS} from '../facts';
import {font} from '../theme';

/**
 * FILM 8 — "SILK". Fifteen seconds at SIXTY frames per second, cut to answer a
 * specific complaint: that the other films are not as smooth as the reference
 * ad we were shown.
 *
 * That reference was pulled apart frame by frame before a line of this was
 * written, and the smoothness turned out to be five things, four of them free:
 *
 *  1. SIXTY FPS. The reference runs at 59.94. Ours ran at 30. A move that takes
 *     four frames there takes two here, and two samples of a fast move is a
 *     stutter no easing curve can hide. This is the one that is not free: the
 *     render is twice the frames and the file is roughly twice the size.
 *
 *  2. NO CUTS. Not one, in twelve seconds. Every scene change goes THROUGH a
 *     bloomed defocus: the outgoing frame blurs, blows out and shrinks a
 *     couple of per cent while the incoming one resolves out of the same haze.
 *     There is no instant at which a hard edge moves, so there is no seam for
 *     the eye to catch. F6 has five hard cuts and three flash cuts.
 *
 *  3. ONE CURVE FOR EVERYTHING. In the reference's opening, the mark's scale,
 *     its exposure, its blur, the background wash and the wordmark's sharpness
 *     all resolve on the same ramp. Ours animated one property at a time — a
 *     slice would fall while its brightness and focus sat still, which reads as
 *     a sticker sliding rather than an object arriving.
 *
 *  4. ARRIVE HOT AND OVERSIZED. Nothing in the reference fades up at its final
 *     size. Everything arrives a few per cent too big, too bright and out of
 *     focus, then settles. That settle is the whole feeling.
 *
 *  5. ONE THING ON SCREEN. The reference holds a single centred subject for
 *     two to three seconds at a time. F6's waterfall has twelve slices moving
 *     at once; the eye has nowhere to rest and reads it as busy, not smooth.
 *
 * What is NOT borrowed: the reference is an advertisement for another product,
 * and none of its identity is here. No starburst, no wordmark, no copy, no
 * model names. The mark is `web/public/favicon.svg`, the amber is the app's,
 * every screen is a screenshot of this client, and every claim comes from
 * `facts.ts` like all the others. Technique is fair to learn; a brand is not.
 */

export const SILK_FRAMES = 900; // 15s at 60fps
export const SILK_FPS = 60;

const S = {
  bg: '#04060A',
  ink: '#EEF2F8',
  dim: '#8792A3',
  faint: '#4A5361',
  neon: '#FF8A3D',
};

/** One curve, everywhere. Nothing in this film uses a different one. */
const EASE = Easing.bezier(0.32, 0, 0.12, 1);

const ramp = (f: number, s: number, l: number) =>
  interpolate(f, [s, s + l], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: EASE,
  });

/* ================================================================== */
/* The dissolve                                                        */

/**
 * Both halves of the transition, as CSS.
 *
 * The numbers are large on purpose. 24px of blur and 2.7x exposure sound like
 * a lot written down, and at 60fps across 40 frames they are gone before you
 * can name them — what survives is the impression that the picture went soft
 * and bright for a moment. Tuned down to something that looks reasonable in a
 * still, the effect disappears entirely in motion, which is the same trap the
 * shot-card library warns about for every other parameter.
 */
const OVERLAP = 40;

const entering = (t: number): React.CSSProperties => ({
  opacity: Math.min(1, t * 2.2),
  transform: `scale(${1.05 - 0.05 * t})`,
  filter: `blur(${(1 - t) * 24}px) brightness(${1 + (1 - t) * 1.7}) saturate(${1 + (1 - t) * 0.6})`,
});

const leaving = (t: number): React.CSSProperties => ({
  opacity: 1 - Math.min(1, t * 1.7),
  transform: `scale(${1 - 0.042 * t})`,
  filter: `blur(${t * 26}px) brightness(${1 + t * 2.0}) saturate(${1 + t * 0.6})`,
});

/**
 * Arrive hot and oversized, then settle — the reference's signature, and the
 * one move this film uses for every element that is not a whole scene.
 */
const settle = (f: number, start: number, dur: number, from = 1.5): React.CSSProperties => {
  const t = ramp(f, start, dur);
  return {
    opacity: Math.min(1, t * 2.6),
    transform: `scale(${from - (from - 1) * t})`,
    filter: `blur(${(1 - t) * 18}px) brightness(${1 + (1 - t) * 2.4})`,
  };
};

/* ================================================================== */
/* Scenes                                                              */

/** A whole plate, drifting. Nothing in this film is ever completely still. */
const Plate: React.FC<{src: string; f: number; from: number; to: number; ox?: string}> = ({
  src,
  f,
  from,
  to,
  ox = '50% 50%',
}) => {
  const k = interpolate(f, [0, 220], [from, to], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.4, 1),
  });
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
      <Img
        src={staticFile(src)}
        style={{
          width: 1920 * k,
          transform: `translateZ(0)`,
          transformOrigin: ox,
          borderRadius: 14,
          boxShadow: '0 40px 160px rgba(0,0,0,0.7)',
        }}
      />
    </AbsoluteFill>
  );
};

/** One line, resolving out of the same haze everything else does. */
const Line: React.FC<{f: number; at: number; text: string; sub?: boolean}> = ({
  f,
  at,
  text,
  sub,
}) => (
  <div
    style={{
      position: 'absolute',
      left: 0,
      right: 0,
      bottom: sub ? 96 : 128,
      textAlign: 'center',
      fontFamily: sub ? font.mono : font.sans,
      fontSize: sub ? 20 : 34,
      letterSpacing: sub ? '0.14em' : '-0.01em',
      color: sub ? S.faint : S.ink,
      textShadow: '0 6px 40px rgba(0,0,0,0.9)',
      ...settle(f, at, 46, 1.06),
    }}
  >
    {text}
  </div>
);

/* 1 — a point of light becomes the mark ---------------------------- */

const Ignite: React.FC<{f: number}> = ({f}) => {
  const spark = ramp(f, 10, 46);
  const markT = ramp(f, 54, 64);
  // the spark is consumed by the mark rather than fading beside it
  const sparkOut = ramp(f, 54, 30);
  const size = 300;

  return (
    <AbsoluteFill style={{background: S.bg}}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(${60 + spark * 520}px ${60 + spark * 520}px at 50% 46%, rgba(255,180,110,${0.42 * spark * (1 - sparkOut * 0.8)}) 0%, rgba(255,138,61,0) 70%)`,
        }}
      />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
        <div
          style={{
            marginTop: -80,
            opacity: Math.min(1, markT * 2.6),
            transform: `scale(${2.3 - 1.3 * markT})`,
            filter: `blur(${(1 - markT) * 26}px) brightness(${1 + (1 - markT) * 2.8})`,
          }}
        >
          <Mark frame={f - 54} size={size} live tone={S.neon} />
        </div>
      </AbsoluteFill>

      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 660,
          textAlign: 'center',
          fontFamily: font.sans,
          fontSize: 88,
          fontWeight: 700,
          letterSpacing: '-0.045em',
          color: S.ink,
          ...settle(f, 116, 56, 1.14),
        }}
      >
        {PRODUCT.name}
      </div>
      <Line f={f} at={148} text={PRODUCT.tagline.toUpperCase()} sub />
    </AbsoluteFill>
  );
};

/* 2..4 — the client, one page at a time ---------------------------- */

const Ask: React.FC<{f: number}> = ({f}) => (
  <AbsoluteFill style={{background: S.bg}}>
    <Plate src="rec/home.jpg" f={f} from={0.72} to={0.86} />
    <Line f={f} at={40} text={PRODUCT.what} />
  </AbsoluteFill>
);

const Raise: React.FC<{f: number}> = ({f}) => (
  <AbsoluteFill style={{background: S.bg}}>
    <Plate src="rec/create.jpg" f={f} from={0.88} to={0.74} />
    <Line f={f} at={40} text={SPAWNS.howMany} />
  </AbsoluteFill>
);

const Many: React.FC<{f: number}> = ({f}) => (
  <AbsoluteFill style={{background: S.bg}}>
    <Plate src="rec/ledger.jpg" f={f} from={0.94} to={0.78} />
    <Line f={f} at={40} text={SPAWNS.equip} />
  </AbsoluteFill>
);

/* 5 — the close ---------------------------------------------------- */

const Close: React.FC<{f: number}> = ({f}) => (
  <AbsoluteFill style={{background: S.bg}}>
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
      <div style={{marginTop: -170, ...settle(f, 6, 56, 1.5)}}>
        <Mark frame={f - 6} size={150} live tone={S.neon} />
      </div>
    </AbsoluteFill>

    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        top: 566,
        textAlign: 'center',
        fontFamily: font.sans,
        fontSize: 92,
        fontWeight: 720,
        letterSpacing: '-0.05em',
        color: S.ink,
        ...settle(f, 34, 52, 1.1),
      }}
    >
      {PRODUCT.name}
    </div>

    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        top: 690,
        textAlign: 'center',
        ...settle(f, 62, 52, 1.08),
      }}
    >
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 14,
          padding: '20px 42px',
          borderRadius: 999,
          background: S.neon,
          color: '#160A02',
          fontFamily: font.sans,
          fontSize: 27,
          fontWeight: 680,
          boxShadow: `0 20px 60px ${S.neon}44`,
        }}
      >
        <span>↓</span> Download for macOS
      </span>
    </div>

    <Line
      f={f}
      at={92}
      sub
      text={`${PRODUCT.platform} · ${PRODUCT.license} · ${PRODUCT.status}`}
    />
  </AbsoluteFill>
);

/* ================================================================== */

const SCENES = [
  {at: 0, C: Ignite},
  {at: 200, C: Ask},
  {at: 380, C: Raise},
  {at: 560, C: Many},
  {at: 740, C: Close},
];

export const Silk: React.FC = () => {
  const f = useCurrentFrame();

  // Every scene whose window — including the overlap it leaves through — covers
  // this frame is rendered. Two at a time during a dissolve, one otherwise.
  return (
    <AbsoluteFill style={{background: S.bg}}>
      {SCENES.map((s, i) => {
        const next = SCENES[i + 1];
        const end = next ? next.at + OVERLAP : SILK_FRAMES;
        if (f < s.at || f >= end) return null;

        const inT = i === 0 ? 1 : ramp(f, s.at, OVERLAP);
        const outT = next ? ramp(f, next.at, OVERLAP) : 0;

        const style: React.CSSProperties =
          outT > 0 ? leaving(outT) : inT < 1 ? entering(inT) : {};

        return (
          <AbsoluteFill key={s.at} style={style}>
            <s.C f={f - s.at} />
          </AbsoluteFill>
        );
      })}
    </AbsoluteFill>
  );
};
