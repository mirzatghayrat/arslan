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
import {PRODUCT, SAFETY, SPAWNS} from '../facts';
import {font} from '../theme';

/**
 * FILM 9 — "STAGE". The look of the MiniMax H3 generation, rebuilt so the text
 * on the screens is real.
 *
 * The H3 clip that prompted this is genuinely good in two ways and unusable in
 * a third, and the three have to be separated before anything is decided:
 *
 *  - THE CHARACTER IS AN UPGRADE. 2560x1440 against the 1280x720 we had, and
 *    consistent with the existing creature. The first 3.35 seconds are clean
 *    and are now `public/character/arslan-cat-2k.mp4`. This film opens on it.
 *
 *  - THE STAGING IS WORTH STEALING. A screen floating in black on a reflective
 *    floor, tilted a few degrees, carrying a thick amber rim light, with the
 *    cat sitting beside it. That is the whole reason this film exists.
 *
 *  - THE INTERFACE IS FICTION. Read the Settings panel it generated: AUTOHATION,
 *    COUNECTION, SYSTEN, "Mex replay dispatches", "no coo" where the field says
 *    "no cap", "Lowe blauk for ito cap" where the page says "Leave blank for no
 *    cap", and two full paragraphs that decay into letter shapes. At a glance it
 *    reads as the Arslan settings page. Read it and it is nonsense.
 *
 * The third one is not a prompt problem to be re-rolled. A video model draws
 * what a screen looks like, not what it says, and this repository has a module
 * — `facts.ts` — that exists precisely because four finished films once shipped
 * with invented claims on them. A hallucinated interface is that failure with
 * no fix available: you cannot correct a generated screen with a constant.
 *
 * So the staging is reproduced here in code and every pixel inside every frame
 * is a real 2560x1680 screenshot from `public/rec/`. Same look, true text.
 */

export const STAGE_FRAMES = 1800; // 60s at 30fps

const C = {
  bg: '#03050A',
  ink: '#EFF3F9',
  dim: '#8C97A8',
  faint: '#4C5563',
  amber: '#FF8A3D',
};

const EASE = Easing.bezier(0.33, 0, 0.16, 1);
const ramp = (f: number, s: number, l: number, e = EASE) =>
  interpolate(f, [s, s + l], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: e,
  });

const PLATE = {w: 1920, h: 1260};

/* ================================================================== */

/**
 * The floating screen — the shot the reference is built on.
 *
 * Five layers, and dropping any one of them collapses the effect into a
 * picture with a border:
 *   1. a wide amber bloom behind the panel, blurred to nothing at its edges
 *   2. an extruded slab pushed back in Z, which is what gives the panel a body
 *      instead of an outline
 *   3. the screenshot itself
 *   4. a hard rim on the panel edge, plus an inner rim so the glass has a lip
 *   5. a reflection on the floor, flipped, faded out downward and blurred
 *
 * The reflection is doing more work than it looks: without a floor the panel
 * has nowhere to be, and the shot reads as a slide rather than an object.
 */
const Screen: React.FC<{
  src: string;
  w: number;
  rotY: number;
  x: number;
  y: number;
  glow?: number;
  o?: number;
}> = ({src, w, rotY, x, y, glow = 1, o = 1}) => {
  const h = (PLATE.h / PLATE.w) * w;
  return (
    <div
      style={{
        position: 'absolute',
        left: x - w / 2,
        top: y - h / 2,
        width: w,
        height: h,
        transformStyle: 'preserve-3d',
        transform: `rotateY(${rotY}deg)`,
        opacity: o,
      }}
    >
      {/* 1 — bloom */}
      <div
        style={{
          position: 'absolute',
          inset: -0.09 * w,
          borderRadius: 40,
          background: `radial-gradient(closest-side, ${C.amber}${Math.round(glow * 42).toString(16).padStart(2, '0')}, rgba(0,0,0,0) 72%)`,
          filter: `blur(${0.035 * w}px)`,
        }}
      />
      {/* 2 — the slab, pushed back so the panel has a body */}
      <div
        style={{
          position: 'absolute',
          inset: -10,
          borderRadius: 20,
          background: `linear-gradient(150deg, ${C.amber}, #7a3708 60%, #2a1204)`,
          transform: 'translateZ(-26px)',
          boxShadow: `0 0 ${0.05 * w}px ${C.amber}88`,
        }}
      />
      {/* 3 + 4 — the picture, and its rim */}
      <Img
        src={staticFile(src)}
        style={{width: '100%', height: '100%', display: 'block', borderRadius: 14}}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: 14,
          border: `1.5px solid ${C.amber}cc`,
          boxShadow: `inset 0 0 ${0.03 * w}px rgba(255,138,61,0.22), 0 0 ${0.06 * w}px ${C.amber}55`,
        }}
      />
      {/* 5 — the floor */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: h + 14,
          width: '100%',
          height: h * 0.55,
          transform: 'scaleY(-1)',
          transformOrigin: 'top',
          opacity: 0.16,
          filter: 'blur(3px)',
          maskImage: 'linear-gradient(0deg, transparent 8%, black 92%)',
          WebkitMaskImage: 'linear-gradient(0deg, transparent 8%, black 92%)',
          overflow: 'hidden',
        }}
      >
        <Img src={staticFile(src)} style={{width: '100%', display: 'block'}} />
      </div>
    </div>
  );
};

/** The set: black, one warm pool on the floor, a faint horizon. */
const Room: React.FC<{f: number}> = ({f}) => (
  <>
    <AbsoluteFill style={{background: C.bg}} />
    <AbsoluteFill
      style={{
        background: `radial-gradient(1400px 620px at 50% ${78 + Math.sin(f / 90) * 1.5}%, rgba(255,138,61,0.10) 0%, rgba(255,138,61,0) 70%)`,
      }}
    />
    <AbsoluteFill
      style={{
        background:
          'linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0) 34%, rgba(0,0,0,0) 62%, rgba(2,4,8,0.9) 100%)',
      }}
    />
  </>
);

const Caption: React.FC<{f: number; at: number; text: string}> = ({f, at, text}) => {
  const o = ramp(f, at, 34);
  if (o <= 0.01) return null;
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 78,
        textAlign: 'center',
        fontFamily: font.sans,
        fontSize: 31,
        color: C.ink,
        opacity: o,
        transform: `translateY(${(1 - o) * 14}px)`,
        textShadow: '0 6px 40px rgba(0,0,0,0.95)',
      }}
    >
      {text}
    </div>
  );
};

/* ================================================================== */
/* Scenes                                                              */

const CAT = {src: 'character/arslan-cat-2k.mp4', frames: 100}; // 3.35s at 24fps → 100 at 30

/** Opens on the 2K character. The clip is short, so it holds on its last frame. */
const Creature: React.FC<{f: number}> = ({f}) => {
  const k = interpolate(f, [0, 200], [1.04, 1.15], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.4, 1),
  });
  const o = ramp(f, 0, 30);
  return (
    <AbsoluteFill style={{background: C.bg, overflow: 'hidden'}}>
      <AbsoluteFill style={{opacity: o, transform: `scale(${k})`}}>
        <Freeze frame={Math.min(f, CAT.frames - 1)}>
          <OffthreadVideo
            src={staticFile(CAT.src)}
            muted
            style={{width: '100%', height: '100%', objectFit: 'cover'}}
          />
        </Freeze>
      </AbsoluteFill>
      {/* sink the bright wall into the film's black so the cut into the dark
          stage is a dimmer rather than a change of world */}
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(1100px 760px at 50% 46%, rgba(3,5,10,0) 0%, rgba(3,5,10,0.55) 58%, rgba(3,5,10,0.97) 100%)',
          opacity: 0.5 + ramp(f, 120, 80) * 0.5,
        }}
      />
      <div
        style={{
          position: 'absolute',
          right: 64,
          bottom: 52,
          fontFamily: font.mono,
          fontSize: 15,
          letterSpacing: '0.1em',
          color: 'rgba(239,243,249,0.32)',
          opacity: o,
        }}
      >
        BRAND CHARACTER · GENERATED IMAGERY
      </div>
    </AbsoluteFill>
  );
};

/** One screen on the stage, drifting, with a slow orbit. */
const Solo: React.FC<{f: number; src: string; text: string; dir?: number}> = ({
  f,
  src,
  text,
  dir = 1,
}) => {
  const rot = interpolate(f, [0, 220], [-20 * dir, -9 * dir], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.4, 1),
  });
  const w = interpolate(f, [0, 220], [1180, 1320], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.4, 1),
  });
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      <Room f={f} />
      <AbsoluteFill style={{perspective: 2000, perspectiveOrigin: '50% 44%'}}>
        <Screen src={src} w={w} rotY={rot} x={960} y={478} o={ramp(f, 0, 26)} />
      </AbsoluteFill>
      <Caption f={f} at={44} text={text} />
    </AbsoluteFill>
  );
};

/** The two-shot the reference closes on: the creature beside the screen. */
const TwoShot: React.FC<{f: number}> = ({f}) => {
  const o = ramp(f, 0, 30);
  const rot = interpolate(f, [0, 240], [-26, -14], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.3, 0, 0.4, 1),
  });
  const catW = 720;
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      <Room f={f} />

      <div
        style={{
          position: 'absolute',
          left: 132,
          top: 540 - (catW * 9) / 16 / 2,
          width: catW,
          height: (catW * 9) / 16,
          overflow: 'hidden',
          borderRadius: 10,
          border: `1px solid ${C.amber}33`,
          boxShadow: `0 0 110px ${C.amber}18`,
          opacity: o,
        }}
      >
        <Freeze frame={CAT.frames - 1}>
          <OffthreadVideo
            src={staticFile(CAT.src)}
            muted
            style={{width: '100%', height: '100%', objectFit: 'cover'}}
          />
        </Freeze>
        <AbsoluteFill
          style={{background: 'radial-gradient(70% 70% at 50% 45%, rgba(3,5,10,0) 0%, rgba(3,5,10,0.8) 100%)'}}
        />
      </div>

      <AbsoluteFill style={{perspective: 2000, perspectiveOrigin: '62% 46%'}}>
        <Screen src="rec/auto.jpg" w={1000} rotY={rot} x={1330} y={512} o={ramp(f, 18, 30)} />
      </AbsoluteFill>

      <Caption f={f} at={52} text={SAFETY.local} />
    </AbsoluteFill>
  );
};

const Cta: React.FC<{f: number}> = ({f}) => {
  const a = ramp(f, 6, 34);
  const b = ramp(f, 34, 34);
  const c = ramp(f, 62, 30);
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      <Room f={f} />
      <AbsoluteFill
        style={{
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'column',
          fontFamily: font.sans,
        }}
      >
        <div
          style={{
            fontSize: 124,
            fontWeight: 720,
            letterSpacing: '-0.05em',
            color: C.ink,
            opacity: a,
            transform: `translateY(${(1 - a) * 22}px)`,
          }}
        >
          {PRODUCT.name}
        </div>
        <div style={{marginTop: 12, fontSize: 29, color: C.dim, opacity: a}}>
          {PRODUCT.tagline}
        </div>
        <div
          style={{
            marginTop: 46,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 15,
            padding: '22px 46px',
            borderRadius: 999,
            background: C.amber,
            color: '#160A02',
            fontSize: 29,
            fontWeight: 680,
            opacity: b,
            transform: `translateY(${(1 - b) * 16}px)`,
            boxShadow: `0 22px 70px ${C.amber}55`,
          }}
        >
          <span>↓</span> Download for macOS
        </div>
        <div
          style={{
            marginTop: 22,
            fontFamily: font.mono,
            fontSize: 17,
            letterSpacing: '0.07em',
            color: C.faint,
            opacity: c,
          }}
        >
          {PRODUCT.platform} · {PRODUCT.license} · {PRODUCT.status}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/* ================================================================== */

const BEATS: {at: number; render: (f: number) => React.ReactNode}[] = [
  {at: 0, render: (f) => <Creature f={f} />},
  {at: 230, render: (f) => <Solo f={f} src="rec/home.jpg" text={PRODUCT.what} />},
  {at: 460, render: (f) => <Solo f={f} src="rec/create.jpg" text={SPAWNS.howMany} dir={-1} />},
  {at: 690, render: (f) => <Solo f={f} src="rec/ledger.jpg" text="Every spawn you raised, on one page." />},
  {at: 920, render: (f) => <Solo f={f} src="rec/mcp.jpg" text={SPAWNS.equip} dir={-1} />},
  {at: 1150, render: (f) => <Solo f={f} src="rec/diag.jpg" text="Every run, timed and costed." />},
  {at: 1380, render: (f) => <TwoShot f={f} />},
  {at: 1620, render: (f) => <Cta f={f} />},
];

/** Bloomed defocus between beats — the F8 lesson, kept. */
const OVER = 26;
const entering = (t: number): React.CSSProperties => ({
  opacity: Math.min(1, t * 2.2),
  transform: `scale(${1.035 - 0.035 * t})`,
  filter: `blur(${(1 - t) * 18}px) brightness(${1 + (1 - t) * 1.3})`,
});
const leaving = (t: number): React.CSSProperties => ({
  opacity: 1 - Math.min(1, t * 1.7),
  transform: `scale(${1 - 0.03 * t})`,
  filter: `blur(${t * 20}px) brightness(${1 + t * 1.5})`,
});

export const Stage: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{background: C.bg}}>
      {BEATS.map((b, i) => {
        const next = BEATS[i + 1];
        const end = next ? next.at + OVER : STAGE_FRAMES;
        if (f < b.at || f >= end) return null;
        const inT = i === 0 ? 1 : ramp(f, b.at, OVER);
        const outT = next ? ramp(f, next.at, OVER) : 0;
        const style = outT > 0 ? leaving(outT) : inT < 1 ? entering(inT) : {};
        return (
          <AbsoluteFill key={b.at} style={style}>
            {b.render(f - b.at)}
          </AbsoluteFill>
        );
      })}
    </AbsoluteFill>
  );
};
